"""
ingestion/extractors/aaaplay.py

Collects the DS-09 payload from the AAA Play WordPress REST API.

ONE OBJECT, NOT FOUR
    This module returns a single JSON document holding all three post types and
    the four taxonomies. That is not a packaging preference, it is what the rest
    of the pipeline requires.

    The load handler is triggered per S3 object and opens one transaction per
    object. Writing activity, facility, organisation and taxonomy files
    separately would raise four ObjectCreated events for one logical pull, and
    the activity event would arrive with no way to resolve a facility id or a
    term id, because those live in files the transformer cannot see. Worse, the
    four loads would race: a transaction that inserts programmes before the
    facilities transaction commits fails on a foreign key.

    Collapsing to one object also leaves the existing change detection alone. A
    single body has a single SHA-256, so the fetch handler's conditional path,
    its manifest and the quiet-week behaviour all work exactly as they do for
    DS-01 and DS-02, with no special case for an API source.

EIGHTEEN REQUESTS, NOT FOURTEEN
    Six pages of activities, six of facilities, two of organisations, then one
    each for the four taxonomies. The source assessment of 11 September says
    fourteen, which counts the post-type pages and forgets the taxonomies.

NO THIRD-PARTY HTTP CLIENT
    urllib only. requests is not in the Lambda runtime and adding a layer for
    eighteen GETs is not worth the deployment surface.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

LOG = logging.getLogger("sportable.fetch.aaaplay")

BASE_URL = "https://aaaplay.org.au/wp-json/wp/v2"

# Post types collected in full, in the order a reader would want them.
POST_TYPES = ("activity", "facility", "organisation")

# Taxonomies are term id to term name maps. Small, and needed to resolve the
# integer ids the post types carry.
TAXONOMIES = ("activity_type", "age_range", "lga", "region")

PER_PAGE = 100

# WordPress does not document a rate limit on these endpoints and the whole pull
# is eighteen requests, but a small pause keeps a retry storm from looking like
# an attack to anything sitting in front of the origin. The site runs Wordfence,
# so being unremarkable matters more here than finishing quickly.
PAUSE_SECONDS = 0.25

# Generous, because a cold WordPress page-one can be slow, and a timeout part
# way through pagination throws away the pages already fetched.
TIMEOUT_SECONDS = 60

MAX_ATTEMPTS = 3

# A guard against an upstream change turning pagination into a loop. The real
# collections are six pages each; anything past this is a bug, not a big day.
MAX_PAGES = 40

# SHORT AND PLAIN, ON PURPOSE. The publisher runs Wordfence, and a longer
# descriptive User-Agent — "SportAbleMelbourne/1.0 (Monash University student
# project; accessible sport and recreation discovery)" — is answered with a
# blanket 403 while this one gets a 200. A bot User-Agent carrying a project URL
# is accepted, so automated access is not being refused; a heuristic in the
# firewall is matching on the prose.
#
# Do NOT resolve a future 403 by impersonating a browser. Claiming to be Chrome
# would work and would also be a lie told to a publisher we have not asked for
# permission yet. Identify honestly, and if identifying honestly stops working,
# that is the publisher saying no and it belongs in the conversation with
# Reclink rather than in this constant.
USER_AGENT = "SportAbleMelbourne/1.0"

# Wordfence also answers a request carrying no Accept header more suspiciously
# than one that states what it wants. This is what the endpoint returns anyway.
ACCEPT = "application/json"


class FetchError(RuntimeError):
    """Raised when the API cannot be collected completely."""


def _default_transport(url: str) -> tuple[int, dict[str, str], bytes]:
    """Perform one GET. Returns status, headers and body."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": ACCEPT},
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return (
                response.status,
                {k.lower(): v for k, v in response.headers.items()},
                response.read(),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            {k.lower(): v for k, v in (error.headers or {}).items()},
            error.read() or b"",
        )


def _get_json(
    url: str,
    transport: Callable[[str], tuple[int, dict[str, str], bytes]],
) -> tuple[Any, dict[str, str]]:
    """GET one URL, retrying on transient failures only.

    A 4xx is not retried. WordPress answers a page past the end with a 400 and
    rest_post_invalid_page_number, which is a terminator rather than a fault,
    and retrying a 404 three times only delays the error.
    """
    last_status = 0
    last_body = b""
    made = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        made = attempt
        status, headers, body = transport(url)

        if status == 200:
            try:
                return json.loads(body.decode("utf-8")), headers
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise FetchError(f"{url} returned a 200 that is not JSON: {error}") from error

        last_status, last_body = status, body

        if 400 <= status < 500:
            break

        if attempt < MAX_ATTEMPTS:
            time.sleep(PAUSE_SECONDS * attempt)

    raise FetchError(
        f"{url} returned HTTP {last_status} after {made} attempt(s): {last_body[:200]!r}"
    )


def _collect_paginated(
    collection: str,
    transport: Callable[[str], tuple[int, dict[str, str], bytes]],
) -> list[dict[str, Any]]:
    """Page a WordPress collection to exhaustion.

    Pagination stops on the X-WP-TotalPages header rather than on the first
    error. Paging until a 400 works, but it makes a genuine upstream failure
    indistinguishable from the end of the data, and a truncated pull that looks
    successful is the failure mode this whole pipeline is built to avoid.
    """
    records: list[dict[str, Any]] = []
    total_pages: int | None = None
    page = 1

    while page <= MAX_PAGES:
        query = urllib.parse.urlencode({"per_page": PER_PAGE, "page": page})
        url = f"{BASE_URL}/{collection}?{query}"

        payload, headers = _get_json(url, transport)

        if not isinstance(payload, list):
            raise FetchError(f"{url} returned {type(payload).__name__}, expected a list")

        records.extend(payload)

        if total_pages is None:
            try:
                total_pages = int(headers.get("x-wp-totalpages", "1"))
            except ValueError as error:
                raise FetchError(
                    f"{url} returned an unreadable X-WP-TotalPages header: "
                    f"{headers.get('x-wp-totalpages')!r}"
                ) from error

            expected = headers.get("x-wp-total")
            LOG.info("%s: %s records across %s pages", collection, expected, total_pages)

        if page >= total_pages:
            break

        page += 1
        time.sleep(PAUSE_SECONDS)

    else:
        raise FetchError(
            f"{collection} exceeded {MAX_PAGES} pages. The real collections are "
            "six pages, so this is an upstream change or a pagination loop, not "
            "a large day. Refusing to keep requesting."
        )

    if not records:
        raise FetchError(
            f"{collection} returned no records. An empty collection is not a "
            "quiet week: the fetch writes no payload when the SHA is unchanged, "
            "so an empty list here means the pull is broken and must not be "
            "written as though it were the current state of the register."
        )

    return records


def collect(
    transport: Callable[[str], tuple[int, dict[str, str], bytes]] | None = None,
) -> bytes:
    """Collect the whole DS-09 payload as one JSON document.

    Returns UTF-8 bytes ready to hash and put. Keys are sorted and separators
    fixed so that an unchanged register produces a byte-identical body and
    therefore an unchanged SHA-256. Without that, dictionary ordering alone
    would make every week look like a change and trigger a pointless load.
    """
    send = transport or _default_transport

    document: dict[str, Any] = {
        "source_id": "DS-09",
        "base_url": BASE_URL,
        "post_types": {},
        "taxonomies": {},
    }

    for collection in POST_TYPES:
        document["post_types"][collection] = _collect_paginated(collection, send)
        time.sleep(PAUSE_SECONDS)

    for taxonomy in TAXONOMIES:
        # Taxonomies are one page each. They are collected through the same
        # paginator so that a taxonomy which outgrows a page is not silently
        # truncated, which would drop term names and leave programmes labelled
        # with nothing.
        document["taxonomies"][taxonomy] = _collect_paginated(taxonomy, send)
        time.sleep(PAUSE_SECONDS)

    counts = {name: len(rows) for name, rows in document["post_types"].items()}
    LOG.info("DS-09 collected %s", counts)

    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def split(payload: bytes) -> dict[str, Any]:
    """Unpack a collected document into the arguments ds09_aaaplay.transform takes.

    Lives beside collect so the shape is defined once. The load handler calls
    this; nothing else should need to know the document layout.
    """
    document = json.loads(payload.decode("utf-8"))
    post_types = document.get("post_types") or {}

    return {
        "activities": post_types.get("activity") or [],
        "facilities": post_types.get("facility") or [],
        "organisations": post_types.get("organisation") or [],
        "taxonomy_terms": document.get("taxonomies") or {},
    }
