"""Fetch one open-data source and land it, unmodified, in the S3 raw zone.

WHERE THIS RUNS, AND WHY IT MATTERS
    OUTSIDE the VPC. It is the only Lambda in this project with a route to the
    internet, because it is the only one that needs to reach a public portal.

    Its sibling, `load`, runs INSIDE the VPC so it can reach RDS, and gets to S3
    through the gateway endpoint. Neither needs a NAT Gateway. That split is the
    whole reason ingestion costs nothing to run — see ADR-002.

WHAT IT DELIBERATELY DOES NOT DO
    It does not parse, validate, reshape or filter. The bytes that arrive from
    the publisher are the bytes written to S3.

    That is what makes the raw zone worth having: when a transform turns out to
    be wrong in three weeks, the original response is still there and the fix is
    a re-run rather than a re-fetch. Publishers overwrite their files; we cannot
    ask them for last month's version.

THE ONE THING TO COPY FROM THIS FILE
    Every network call has an explicit timeout. An earlier version of the API
    handler called Parameter Store with no bound, from a subnet with no route to
    it — the call did not fail, it HUNG, and the function timeout turned the
    request into a 500. A `try/except` catches failures; a hang is not one.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

import boto3

# Seconds. Deliberately well under the function's own timeout, so a slow
# publisher produces a clean error we can read rather than an opaque Lambda
# timeout with no traceback.
_HTTP_TIMEOUT_SECONDS = 20

# Government open-data portals routinely reject the default urllib agent.
_USER_AGENT = "SportAble-Melbourne/1.0 (FIT5120 student project)"

_RAW_BUCKET = os.environ.get("RAW_BUCKET", "")

# {"vic_sport_rec": "https://...", ...}, resolved by Terraform at apply time
# from the source registry. Same pattern as the API's SEARCH_CONFIG: this
# function could reach Parameter Store, but keeping both handlers consistent is
# worth more than the one-minute-fresher config.
_SOURCES: dict[str, str] = json.loads(os.environ.get("SOURCES", "{}"))


def _partition() -> str:
    """Return today's Hive-style partition, e.g. `dt=2026-08-30`.

    UTC, not local time. A partition that shifts with daylight saving produces
    two folders for one day every October, and the load step silently processes
    one of them.
    """
    return f"dt={datetime.now(UTC).strftime('%Y-%m-%d')}"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Fetch one source and write it to the raw zone.

    Args:
        event: `{"dataset": "vic_sport_rec"}`. EventBridge supplies this as a
            constant per rule. An optional `"url"` overrides the configured one,
            which is how the smoke test in the runbook proves the path without
            depending on a publisher being up.
        context: Lambda context. Unused.

    Returns:
        A summary including the key written. Returned rather than logged alone
        so a manual `aws lambda invoke` shows the result directly.

    Raises:
        ValueError: the dataset is unknown or has no URL configured. Raising is
            correct here — a scheduled fetch that quietly does nothing is how a
            pipeline appears healthy for a fortnight while the database stays
            empty.
    """
    dataset = event.get("dataset")
    if not dataset:
        raise ValueError("event must carry a 'dataset'")

    url = event.get("url") or _SOURCES.get(dataset)
    if not url:
        raise ValueError(
            f"no URL configured for dataset '{dataset}'. "
            f"Set it in infra/envs/staging/main.tf under module.ingestion.sources."
        )

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        # nosec B310 - the URL comes from our own Terraform-managed config,
        # never from user input.
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "application/octet-stream")
    except urllib.error.URLError as exc:
        # Re-raised, not swallowed. The Lambda error metric is what the
        # CloudWatch alarm watches; returning a cheerful 200 here would make the
        # failure invisible.
        raise RuntimeError(f"fetch failed for {dataset} from {url}: {exc}") from exc

    # The filename the publisher used, or the dataset name if the URL has no
    # useful last segment.
    filename = url.rstrip("/").rsplit("/", 1)[-1] or dataset
    key = f"{dataset}/{_partition()}/{filename}"

    boto3.client("s3").put_object(
        Bucket=_RAW_BUCKET,
        Key=key,
        Body=body,
        ContentType=content_type,
        Metadata={
            "source-url": url[:1024],
            "fetched-at": datetime.now(UTC).isoformat(),
            "dataset": dataset,
        },
    )

    result = {
        "dataset": dataset,
        "bucket": _RAW_BUCKET,
        "key": key,
        "bytes": len(body),
        "content_type": content_type,
    }
    print(f"fetch: {json.dumps(result)}")
    return result
