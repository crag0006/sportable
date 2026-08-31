"""
Fetch source files and store them in the raw zone.

The source details come from the YAML source cards.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import yaml


LOG = logging.getLogger()
LOG.setLevel(logging.INFO)

s3 = boto3.client("s3")

RAW_BUCKET = os.environ.get("RAW_BUCKET", "")
REGISTER_DIR = Path(
    os.environ.get("REGISTER_DIR", Path(__file__).parent / "sources")
)

MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
BACKOFF_BASE_SECONDS = 2
READ_CHUNK = 1024 * 1024

USER_AGENT = "SportAbleMelbourne-Fetch/1.0"

FETCHABLE_TIERS = {"reference", "transit", "static"}

# Status codes that must never be retried. A 429 from the Opendatasoft portals
# is a monthly quota exhaustion, not a rate limit that clears in seconds, so
# retrying with backoff burns the remaining quota and delays the alarm. It fails
# immediately and lets the previous snapshot stand.
NO_RETRY_STATUS = {429}


class FetchError(RuntimeError):
    pass


class NotFetchable(ValueError):
    pass


def load_source_card(source_id: str) -> dict[str, Any]:
    matches = sorted(REGISTER_DIR.glob(f"{source_id}_*.yaml"))

    if not matches:
        raise FileNotFoundError(
            f"No source card found for {source_id} in {REGISTER_DIR}"
        )

    card = yaml.safe_load(
        matches[0].read_text(encoding="utf-8")
    )

    if card.get("source_id") != source_id:
        raise ValueError(
            f"{matches[0].name} has a different source_id"
        )

    if not card.get("publisher"):
        raise ValueError(f"{source_id} has no publisher")

    licence = card.get("licence", {})

    # DMP section 3.3: the load is abandoned if any registered source is missing
    # a licence. A card carrying UNVERIFIED is a card that has not passed the
    # section 4.1 gate, and it must fail here rather than land and be sorted out
    # afterwards.
    if not licence.get("name") or not licence.get("url"):
        raise ValueError(f"{source_id} has an incomplete licence")

    if str(licence.get("name")).strip().upper() == "UNVERIFIED":
        raise ValueError(
            f"{source_id} licence is recorded as UNVERIFIED and has not passed "
            f"the section 4.1 verification gate"
        )

    retrieval = card.get("retrieval", {})
    if not retrieval.get("download_url"):
        raise ValueError(f"{source_id} has no download URL")

    if not retrieval.get("format"):
        raise ValueError(f"{source_id} has no retrieval format")

    if not retrieval.get("raw_prefix"):
        raise ValueError(f"{source_id} has no raw_prefix")

    return card


def resolve_download_url(
    card: dict[str, Any]
) -> tuple[str, dict[str, Any]]:

    retrieval = card["retrieval"]
    resolver = retrieval.get("resolver", "static_url")

    if resolver == "static_url":
        return retrieval["download_url"], {
            "resolver": "static_url"
        }

    if resolver == "ckan_resource_lookup":
        config = retrieval.get("resolver_config") or {}

        package_id = config.get("package_id")
        if not package_id:
            raise ValueError(
                f"{card['source_id']} has no package_id"
            )

        wanted_format = (
            config.get("format") or "CSV"
        ).upper()

        api_root = (
            config.get("api_root")
            or _ckan_root(retrieval["landing_page"])
        )

        api_url = (
            f"{api_root}/api/3/action/package_show?"
            + urllib.parse.urlencode({"id": package_id})
        )

        body, _ = _http_get(api_url, headers={})
        data = json.loads(body.decode("utf-8"))

        if not data.get("success"):
            raise FetchError(
                f"Could not get CKAN package {package_id}"
            )

        resources = [
            resource
            for resource in data["result"].get("resources", [])
            if (
                (resource.get("format") or "").upper()
                == wanted_format
                and resource.get("url")
            )
        ]

        if not resources:
            raise FetchError(
                f"No {wanted_format} resource found"
            )

        selected = max(
            resources,
            key=lambda x: (
                x.get("last_modified")
                or x.get("created")
                or ""
            ),
        )

        provenance = {
            "resolver": "ckan_resource_lookup",
            "package_id": package_id,
            "resource_id": selected.get("id"),
            "resource_last_modified": (
                selected.get("last_modified")
                or selected.get("created")
            ),
            "registered_url": retrieval["download_url"],
            "url_changed_since_register": (
                selected["url"]
                != retrieval["download_url"]
            ),
        }

        if provenance["url_changed_since_register"]:
            LOG.warning(
                "%s is using a different URL than the one "
                "in the source card",
                card["source_id"],
            )

        return selected["url"], provenance

    raise ValueError(
        f"Unknown resolver {resolver!r}"
    )


def _ckan_root(landing_page: str) -> str:

    head, separator, _ = landing_page.partition(
        "/dataset/"
    )

    if separator:
        return head.rstrip("/")

    parts = urllib.parse.urlsplit(landing_page)

    return f"{parts.scheme}://{parts.netloc}"


def _http_get(
    url: str,
    headers: dict[str, str]
) -> tuple[bytes, dict[str, Any]]:

    request = urllib.request.Request(
        url,
        method="GET"
    )

    request.add_header("User-Agent", USER_AGENT)

    for key, value in headers.items():
        request.add_header(key, value)

    with urllib.request.urlopen(
        request,
        timeout=120
    ) as response:

        chunks = []

        while True:
            chunk = response.read(READ_CHUNK)

            if not chunk:
                break

            chunks.append(chunk)

        body = b"".join(chunks)

        metadata = {
            "status": response.status,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get(
                "Last-Modified"
            ),
            "content_type": response.headers.get(
                "Content-Type"
            ),
            "content_length": response.headers.get(
                "Content-Length"
            ),
            # filename_for() reads this to honour a publisher-supplied filename.
            # Without it that branch never runs and every object falls back to
            # the raw_prefix name.
            "content_disposition": response.headers.get(
                "Content-Disposition"
            ),
            "final_url": response.url,
        }

    return body, metadata


def fetch_with_retry(
    url: str,
    conditional: dict[str, str]
) -> tuple[
    bytes | None,
    dict[str, Any],
    list[dict[str, Any]]
]:

    attempts = []

    for attempt in range(1, MAX_ATTEMPTS + 1):

        started = time.time()

        try:
            body, metadata = _http_get(
                url,
                conditional
            )

            metadata["duration_seconds"] = round(
                time.time() - started,
                3
            )

            attempts.append({
                "attempt": attempt,
                "status": metadata["status"]
            })

            return body, metadata, attempts

        except urllib.error.HTTPError as error:

            attempts.append({
                "attempt": attempt,
                "status": error.code,
                "reason": error.reason,
            })

            if error.code == 304:
                return None, {
                    "status": 304,
                    "etag": conditional.get(
                        "If-None-Match"
                    ),
                    "last_modified": conditional.get(
                        "If-Modified-Since"
                    ),
                    "duration_seconds": round(
                        time.time() - started,
                        3
                    ),
                    "final_url": url,
                }, attempts

            if error.code in NO_RETRY_STATUS:
                raise FetchError(
                    f"{error.code} {error.reason} for {url} - quota or rate "
                    f"limit exhausted, not retried, previous snapshot stands"
                ) from error

            if 400 <= error.code < 500:
                raise FetchError(
                    f"{error.code} {error.reason} for {url}"
                ) from error

        except (
            urllib.error.URLError,
            TimeoutError
        ) as error:

            attempts.append({
                "attempt": attempt,
                "error": str(error)
            })

        if attempt < MAX_ATTEMPTS:

            delay = BACKOFF_BASE_SECONDS ** attempt

            LOG.warning(
                "attempt %d failed for %s, retrying in %ds",
                attempt,
                url,
                delay,
            )

            time.sleep(delay)

    raise FetchError(
        f"All {MAX_ATTEMPTS} attempts failed for {url}"
    )


def check_payload_shape(
    source_id: str,
    body: bytes,
    fmt: str,
    response_meta: dict[str, Any],
) -> None:
    """Reject a 200 response whose body is not the declared format.

    A publisher that has moved, withdrawn or restricted a resource often answers
    with 200 and an HTML page rather than an error status. Nothing downstream
    notices: the body hashes cleanly, lands in the raw zone and writes a success
    manifest. The failure then surfaces days later as an unexplained parse error
    in a notebook. Catching it here keeps a bad publish out of the archive.
    """

    fmt = (fmt or "").lower()
    head = body[:512].lstrip()

    if not body:
        raise FetchError(f"{source_id} returned an empty body")

    if head[:14].lower().startswith(b"<!doctype html") or head[:5].lower() == b"<html":
        if fmt not in {"html", "htm"}:
            raise FetchError(
                f"{source_id} returned an HTML page, not {fmt}. The resource may "
                f"have been withdrawn, moved or made private."
            )

    if fmt in {"kml", "xml", "gpx"} and not head.startswith(b"<"):
        raise FetchError(
            f"{source_id} declares {fmt} but the body does not begin with an XML tag"
        )

    if fmt in {"zip", "kmz", "xlsx", "shp"} and not body.startswith(b"PK"):
        raise FetchError(
            f"{source_id} declares {fmt} but the body carries no zip signature"
        )

    if fmt == "json" and head[:1] not in (b"{", b"["):
        raise FetchError(
            f"{source_id} declares json but the body does not begin with an object or array"
        )

    if fmt == "csv" and head.startswith(b"PK"):
        raise FetchError(
            f"{source_id} declares csv but the body is a zip archive"
        )


def object_key(
    raw_prefix: str,
    run_date: str,
    filename: str
) -> str:

    return f"{raw_prefix}/dt={run_date}/{filename}"


def manifest_key(
    raw_prefix: str,
    run_date: str,
    run_id: str
) -> str:

    return (
        f"_manifests/{raw_prefix}/dt={run_date}/"
        f"run-{run_id}.json"
    )


def latest_manifest_key(raw_prefix: str) -> str:
    return f"_manifests/{raw_prefix}/latest.json"


def read_latest_manifest(
    raw_prefix: str
) -> dict[str, Any] | None:

    try:
        response = s3.get_object(
            Bucket=RAW_BUCKET,
            Key=latest_manifest_key(raw_prefix)
        )

        return json.loads(
            response["Body"].read().decode("utf-8")
        )

    except s3.exceptions.NoSuchKey:
        return None

    except Exception as error:
        LOG.warning(
            "Could not read latest manifest for %s: %s",
            raw_prefix,
            error,
        )
        return None


def json_default(value: Any) -> str:

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    raise TypeError(
        f"{type(value).__name__} is not JSON serialisable"
    )


def write_manifest(
    raw_prefix: str,
    run_date: str,
    run_id: str,
    manifest: dict[str, Any]
) -> str:

    body = json.dumps(
        manifest,
        indent=2,
        sort_keys=True,
        default=json_default,
    ).encode("utf-8")

    key = manifest_key(
        raw_prefix,
        run_date,
        run_id
    )

    s3.put_object(
        Bucket=RAW_BUCKET,
        Key=key,
        Body=body,
        ContentType="application/json",
    )

    s3.put_object(
        Bucket=RAW_BUCKET,
        Key=latest_manifest_key(raw_prefix),
        Body=body,
        ContentType="application/json",
    )

    return key


def filename_for(
    card: dict[str, Any],
    url: str,
    response_meta: dict[str, Any]
) -> str:

    disposition = response_meta.get(
        "content_disposition"
    ) or ""

    match = re.search(
        r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?',
        disposition,
    )

    if match:
        filename = match.group(1)
    else:
        filename = Path(
            urllib.parse.urlsplit(url).path
        ).name

    filename = re.sub(
        r"[^A-Za-z0-9._-]",
        "_",
        filename
    ).strip("._")

    expected_extension = (
        "."
        + card["retrieval"]["format"].lower()
    )

    if (
        not filename
        or Path(filename).suffix.lower()
        != expected_extension
    ):
        filename = (
            card["retrieval"]["raw_prefix"]
            + expected_extension
        )

    return filename


def handler(
    event: dict[str, Any],
    context: Any = None
) -> dict[str, Any]:

    if not RAW_BUCKET:
        raise RuntimeError(
            "RAW_BUCKET is not set"
        )

    source_id = event["source_id"]
    force = bool(event.get("force"))

    card = load_source_card(source_id)

    if card.get("tier") not in FETCHABLE_TIERS:
        raise NotFetchable(
            f"{source_id} is not a fetchable source"
        )

    retrieval = card["retrieval"]
    raw_prefix = retrieval["raw_prefix"]

    now = datetime.now(timezone.utc)

    run_date = now.strftime("%Y-%m-%d")
    run_id = now.strftime(
        "%Y%m%dT%H%M%SZ"
    )

    url, url_provenance = resolve_download_url(
        card
    )

    previous = (
        read_latest_manifest(raw_prefix)
        or {}
    )

    conditional = {}

    if not force:

        if previous.get("etag"):
            conditional["If-None-Match"] = (
                previous["etag"]
            )

        elif previous.get("last_modified"):
            conditional["If-Modified-Since"] = (
                previous["last_modified"]
            )

    body, response_meta, attempts = fetch_with_retry(
        url,
        conditional
    )

    manifest = {
        "source_id": source_id,
        "source_name": card.get("name"),
        "publisher": card.get("publisher"),
        "run_id": run_id,
        "run_date": run_date,
        "retrieved_at": now.isoformat(),
        "source_url": url,
        "url_provenance": url_provenance,
        "http": response_meta,
        "attempts": attempts,
        "etag": response_meta.get("etag"),
        "last_modified": response_meta.get(
            "last_modified"
        ),
        # Recorded so the transform and the profiling notebooks can tell a
        # source with no publisher-side change detection from one that simply
        # had not changed. A source offering neither header is hash-only.
        "conditional_get_available": bool(
            response_meta.get("etag")
            or response_meta.get("last_modified")
        ),
        "publisher_last_updated": card.get(
            "publisher_last_updated"
        ),
        "licence": {
            "name": card["licence"].get("name"),
            "version": card["licence"].get("version"),
            "url": card["licence"].get("url"),
        },
        "record_count": None,
        "record_count_deferred_to": "transform",
    }

    if body is None:

        manifest.update({
            "outcome": "no_change",
            "reason": "http_304_not_modified",
            "sha256": previous.get("sha256"),
            "bytes": previous.get("bytes"),
            "object_key": previous.get(
                "object_key"
            ),
            "object_written": False,
        })

        written = write_manifest(
            raw_prefix,
            run_date,
            run_id,
            manifest,
        )

        return {
            "outcome": "no_change",
            "source_id": source_id,
            "manifest_key": written,
        }

    # Verify the body is what the card says it is before anything is hashed,
    # compared or written. A bad publish must not enter the immutable zone.
    check_payload_shape(
        source_id,
        body,
        retrieval["format"],
        response_meta,
    )

    digest = hashlib.sha256(body).hexdigest()

    manifest["sha256"] = digest
    manifest["bytes"] = len(body)

    expected = retrieval.get("expected_sha256")
    if expected:
        manifest["expected_sha256"] = expected
        manifest["sha256_matches_pin"] = (expected == digest)
        if expected != digest:
            LOG.warning(
                "%s payload hash %s does not match the pinned %s",
                source_id,
                digest,
                expected,
            )

    if (
        not force
        and previous.get("sha256") == digest
    ):

        manifest.update({
            "outcome": "no_change",
            "reason": "identical_payload_hash",
            "object_key": previous.get(
                "object_key"
            ),
            "object_written": False,
        })

        written = write_manifest(
            raw_prefix,
            run_date,
            run_id,
            manifest,
        )

        return {
            "outcome": "no_change",
            "source_id": source_id,
            "sha256": digest,
            "manifest_key": written,
        }

    key = object_key(
        raw_prefix,
        run_date,
        filename_for(
            card,
            url,
            response_meta
        ),
    )

    s3.put_object(
        Bucket=RAW_BUCKET,
        Key=key,
        Body=body,
        ContentType=(
            response_meta.get("content_type")
            or "application/octet-stream"
        ),
        Metadata={
            "source-id": source_id,
            "sha256": digest,
            "retrieved-at": now.isoformat(),
            "source-url": url[:1024],
        },
    )

    manifest.update({
        "outcome": "landed",
        "object_key": key,
        "object_written": True,
    })

    written = write_manifest(
        raw_prefix,
        run_date,
        run_id,
        manifest,
    )

    return {
        "outcome": "landed",
        "source_id": source_id,
        "object_key": key,
        "sha256": digest,
        "bytes": len(body),
        "manifest_key": written,
    }