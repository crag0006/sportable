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

TWO COUNT GUARDS, AND THEY ARE NOT THE SAME GUARD
    DS-01 to DS-08 are file downloads with a publisher-stated size and, for
    several of them, a pinned SHA-256. This source is eighteen HTTP responses
    stitched together, so there is no pinned hash to compare against and nothing
    about a short pull looks wrong. A page that returns 200 with fewer records
    than it should produces a smaller payload, a different SHA, an outcome of
    "landed", and a register that quietly loses programmes. Both guards below
    exist to stop that, and they answer different questions.

      1. TRUNCATION, in _collect_paginated. WordPress states the collection size
         in X-WP-Total. If the number of records collected does not equal it,
         the pull contradicts itself and is refused outright. This is a fact
         about one response set, so it is an error and not a warning.

      2. DRIFT, in check_count_drift. Compares this run against the previous
         run's figures from the fetch manifest, and warns loudly beyond ±20%.
         This one cannot be an error: a publisher is allowed to have a big week,
         and a fetch that refuses to write is worse than one that writes and
         shouts, because the load step and the alarm both need the manifest.
         The DS-09 observability alarms read the COUNT_DRIFT log event.

    THE FIRST GUARD IS NOT REDUNDANT, AND HERE IS THE ARITHMETIC. One lost page
    of activities is 100 records out of 532, which is 18.8% and therefore
    INSIDE the 20% band. The drift guard would pass it. A 20% band is a
    sane-range check and was never a truncation detector; the X-WP-Total
    comparison is what catches a lost page, in the same request that lost it.
    Narrowing the band to cover the gap would make a weekly job cry wolf every
    time the register had a busy fortnight.
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

# The band a collection may move within between runs before the fetch says so.
# ±20% as specified in the D1 task note. On the verified figures that is roughly
# a hundred activities either way, which is far wider than any week this
# register has moved and narrow enough to catch a lost page of 100.
DRIFT_TOLERANCE = 0.20

# The collections small enough that a percentage is meaningless. The four
# taxonomies sit here: activity_type is 82 terms, and one term added upstream is
# a 1.2% move, while age_range is 6 and one term is a 17% move that means
# nothing. Below this floor the drift check reports the change and does not call
# it a breach.
DRIFT_FLOOR = 25

# How far the record count may differ from X-WP-Total before the pull is refused
# as truncated. NOT ZERO, and that is deliberate. A six-page pull takes about
# twenty seconds, X-WP-Total is read from page one, and a provider publishing or
# unpublishing a listing in that window shifts the count by one or two. Failing
# the whole fetch on that would make a weekly job flaky for a reason that is not
# a fault. A lost page is a hundred records and is nowhere near this number.
PAGINATION_CHURN = 5

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
    total_records: int | None = None
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

            # X-WP-Total is the publisher's own statement of how many records
            # the collection holds. It is read once, from page one, alongside
            # the page count, and checked against what actually arrived. An
            # unreadable value is left as None rather than guessed at, and the
            # check below then says it could not run.
            try:
                total_records = int(headers.get("x-wp-total", ""))
            except ValueError:
                total_records = None

            LOG.info("%s: %s records across %s pages", collection, total_records, total_pages)

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

    # TRUNCATION CHECK. The publisher said how many records the collection
    # holds; this is the count that actually arrived. A mismatch means the pull
    # contradicts the source it came from, which is a broken pull and not a
    # small register — every one of those responses was a 200, so nothing else
    # in the pipeline would notice. An API source has no pinned file hash the
    # way the file sources do, and this is what stands in its place.
    #
    # A short read is the dangerous direction and a long read is a paging bug,
    # so both fail. If the header was unreadable the check is skipped and says
    # so rather than passing quietly.
    if total_records is None:
        LOG.warning(
            "%s carried no readable X-WP-Total, so the record count could not "
            "be checked against the publisher's own figure",
            collection,
        )

    elif abs(len(records) - total_records) > PAGINATION_CHURN:
        raise FetchError(
            f"{collection} returned {len(records)} records but X-WP-Total says "
            f"{total_records}. The pull disagrees with the publisher about how "
            "much data there is by more than a few mid-pull edits could "
            "explain, which means pages were lost, and a truncated collection "
            "written as the current state of the register would silently delete "
            "programmes. Refusing to return it."
        )

    elif len(records) != total_records:
        # Tolerated, but never unsaid. See PAGINATION_CHURN.
        LOG.warning(
            "%s returned %d records against an X-WP-Total of %d, which is "
            "within the mid-pull churn allowance",
            collection,
            len(records),
            total_records,
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


def record_counts(payload: bytes) -> dict[str, int]:
    """Count the records in a collected payload, by collection.

    Derived from the payload rather than returned alongside it, so the figures
    cannot disagree with the bytes that were hashed and written. The keys are
    the collection names: the three post types and the four taxonomies.
    """
    document = json.loads(payload.decode("utf-8"))

    counts: dict[str, int] = {}

    for group in ("post_types", "taxonomies"):
        for collection, rows in (document.get(group) or {}).items():
            counts[collection] = len(rows or [])

    return counts


def check_count_drift(
    counts: dict[str, int],
    previous: dict[str, int] | None,
    tolerance: float = DRIFT_TOLERANCE,
    baseline: str = "previous_run",
) -> dict[str, Any]:
    """Compare this run's record counts with the previous run's and say so.

    Returns a result the caller puts in the manifest. WARNS, DOES NOT RAISE, and
    the distinction is the point:

        A truncated pull and a genuinely smaller register look identical in the
        numbers. Only a person can tell them apart, and the only way a person
        finds out is if the run says something. Raising would stop the payload
        being written, which loses the very evidence needed to decide, and would
        also stop the manifest that the next run compares against — so one bad
        week would blind the guard for every week after it.

        This is NOT the same as the truncation check in _collect_paginated. That
        one compares a pull against the publisher's own statement of size in the
        same breath, so a mismatch is a contradiction and is refused. This one
        compares two different days, where a difference is allowed to be real.

    `baseline` names where the previous figures came from, because that changes
    how much they are worth. "previous_run" is last week's manifest.
    "source_card" is the verified coverage block, used when no manifest exists,
    which is better than no comparison at all but ages as the register moves.
    No previous figures means no baseline, and that is reported as
    "no_baseline" rather than as a pass: a run with nothing to compare against
    must not look as though it checked something.
    """
    tolerance_pct = round(tolerance * 100, 1)

    result: dict[str, Any] = {
        "baseline": baseline if previous else None,
        "tolerance_pct": tolerance_pct,
        "floor": DRIFT_FLOOR,
        "counts": dict(counts),
        "previous": dict(previous) if previous else None,
        "collections": {},
        "breached": [],
        "appeared": sorted(set(counts) - set(previous or {})) if previous else [],
        "disappeared": sorted(set(previous or {}) - set(counts)),
        "status": "ok",
    }

    if not previous:
        result["status"] = "no_baseline"

        LOG.warning(
            "DS-09 has no previous record counts to compare against, so the "
            "count drift guard did not run. This is expected on a first fetch "
            "and is a missing manifest on any other."
        )

        return result

    for collection in sorted(set(counts) | set(previous)):
        now = counts.get(collection)
        before = previous.get(collection)

        # A collection that appeared or disappeared has no percentage to state.
        # It is reported as the structural change it is, and a disappearance is
        # a breach: the pull stopped collecting something it used to.
        if now is None:
            result["collections"][collection] = {
                "previous": before,
                "current": None,
                "change_pct": None,
                "breached": True,
            }
            result["breached"].append(collection)
            continue

        if before is None or before == 0:
            result["collections"][collection] = {
                "previous": before,
                "current": now,
                "change_pct": None,
                "breached": False,
            }
            continue

        change = round(100 * (now - before) / before, 2)

        # Below the floor a percentage says more about the size of the
        # collection than about the change. Reported, never called a breach.
        breached = abs(now - before) > tolerance * before and before >= DRIFT_FLOOR

        result["collections"][collection] = {
            "previous": before,
            "current": now,
            "change_pct": change,
            "breached": breached,
        }

        if breached:
            result["breached"].append(collection)

    if result["breached"]:
        result["status"] = "drift"

        for collection in result["breached"]:
            moved = result["collections"][collection]

            LOG.error(
                json.dumps(
                    {
                        "event": "COUNT_DRIFT",
                        "source_id": "DS-09",
                        "collection": collection,
                        "previous": moved["previous"],
                        "current": moved["current"],
                        "change_pct": moved["change_pct"],
                        "tolerance_pct": tolerance_pct,
                        "message": (
                            f"DS-09 {collection} moved from {moved['previous']} to "
                            f"{moved['current']} since the previous run, beyond the "
                            f"{tolerance_pct}% band. Either the register really changed "
                            "that much or the pull is short. Check before trusting this "
                            "load."
                        ),
                    },
                    sort_keys=True,
                )
            )

    return result


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
