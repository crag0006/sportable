"""Read a newly landed raw object, record what arrived, and hand off to the loader.

WHERE THIS RUNS
    INSIDE the VPC, in the same private subnet as the API function, so it can
    reach RDS. It gets to S3 through the gateway endpoint — free, and the reason
    no NAT Gateway exists in this account.

    Its sibling, `fetch`, runs OUTSIDE the VPC because it needs the internet.
    Two functions rather than one, purely because of that networking split.

HOW IT IS TRIGGERED
    By an S3 `ObjectCreated` notification on the raw bucket, not by a schedule.
    The fetch step therefore does not need to know this function exists, and a
    file dropped into the bucket by hand is processed exactly like a scheduled
    one — which is what makes the manual fallback in the runbook viable.

WHAT IS DELIBERATELY NOT HERE YET
    The database write.

    This function reads the object, checks it parses, and writes a manifest.
    It does NOT insert rows, for two reasons:

      1. The transform and the column contracts belong to the Data team. There
         is nothing yet to call.
      2. Writing to Postgres needs `psycopg` in the deployment package, and this
         project has no build step that installs dependencies into a Lambda zip.
         `archive_file` zips a directory; it cannot run pip.

    That second reason is shared with the Alembic migration Lambda described in
    the T3 runbook. One build step solves both, and it should be built once
    rather than twice. Until then this function proves the whole path up to the
    database boundary, which is the part that is infrastructure.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime
from typing import Any

import boto3

# Objects larger than this are recorded but not parsed. A GTFS archive is tens
# of megabytes; pulling it into a 512 MB function to count its bytes would risk
# an out-of-memory kill for no benefit.
_MAX_INSPECT_BYTES = 5 * 1024 * 1024

_MANIFEST_PREFIX = "_manifests"


def _inspect(body: bytes, key: str) -> dict[str, Any]:
    """Describe what arrived, without assuming a format.

    Returns a dict rather than raising, because "this file is not what we
    expected" is information the manifest should carry, not a reason to fail the
    invocation. A genuinely broken fetch already failed upstream.
    """
    if key.endswith(".json") or key.endswith(".geojson"):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            return {"format": "json", "parses": False, "error": str(exc)}
        if isinstance(parsed, dict) and "features" in parsed:
            return {
                "format": "geojson",
                "parses": True,
                "features": len(parsed.get("features") or []),
            }
        if isinstance(parsed, list):
            return {"format": "json", "parses": True, "records": len(parsed)}
        return {"format": "json", "parses": True, "keys": sorted(parsed)[:20]}

    if key.endswith(".csv"):
        # Line count, not a CSV parse. Quoted newlines make this an estimate,
        # and an estimate is all a manifest needs — the validators own the real
        # column contract.
        lines = body.count(b"\n")
        return {"format": "csv", "parses": True, "approx_lines": max(lines - 1, 0)}

    return {"format": "unknown", "parses": None}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process every object in an S3 notification.

    Args:
        event: An S3 `ObjectCreated` event. May carry several records.
        context: Lambda context. Unused.

    Returns:
        One summary per object processed.
    """
    s3 = boto3.client("s3")
    results: list[dict[str, Any]] = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        # S3 URL-encodes the key in notifications: a space arrives as "+" and a
        # slash as %2F. Using it raw produces a NoSuchKey on any file whose name
        # is not plain ASCII, which is exactly the kind of bug that only appears
        # once a real publisher is wired up.
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])

        # Our own manifests land in this bucket and would otherwise retrigger
        # this function, which would write another manifest, forever.
        if key.startswith(f"{_MANIFEST_PREFIX}/"):
            continue

        head = s3.head_object(Bucket=bucket, Key=key)
        size = head["ContentLength"]

        if size <= _MAX_INSPECT_BYTES:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            inspection = _inspect(body, key)
        else:
            inspection = {"format": "unknown", "parses": None, "skipped": "too large"}

        manifest = {
            "bucket": bucket,
            "key": key,
            "bytes": size,
            "dataset": key.split("/", 1)[0],
            "observed_at": datetime.now(UTC).isoformat(),
            "inspection": inspection,
            # The honest marker. Until the Data team's loaders exist and psycopg
            # is packaged, nothing reaches Postgres — and this field says so
            # rather than letting a green invocation imply otherwise.
            "rows_loaded": 0,
            "load_status": "pending_loader",
        }

        s3.put_object(
            Bucket=bucket,
            Key=f"{_MANIFEST_PREFIX}/{key}.json",
            Body=json.dumps(manifest, indent=2).encode(),
            ContentType="application/json",
        )

        print(f"load: {json.dumps(manifest)}")
        results.append(manifest)

    return {"processed": len(results), "manifests": results}
