"""Placeholder Lambda handler for the SportAble API.

WHY THIS FILE EXISTS
    Two reasons, and the second matters more than the first.

    1. T2 wires API Gateway to a Lambda. That Terraform needs something
       deployable to point at, and the real FastAPI application is being written
       in parallel. Without this, infrastructure work would block behind
       application work.

    2. It serves DRAFT FIXTURES for the endpoints the Frontend team needs, at
       the real URL, through the real CloudFront and API Gateway path. Both
       frontend engineers can build the search page and the venue card before a
       single endpoint exists.

    API Gateway HTTP APIs cannot do this with a mock integration — that is a
    REST API feature. Confirmed against the API:

        BadRequestException: an API with a protocol type of HTTP may only be
        associated with proxy integrations (AWS_PROXY, HTTP_PROXY)

    So the routing lives here instead, which is better anyway: one place, and it
    is deleted wholesale when the real handler lands.

HOW IT GETS REPLACED
    One line of Terraform. The Lambda's `handler` changes from `stub.handler`
    to the Mangum adapter wrapping the FastAPI app. Nothing about the function,
    its role, its VPC attachment or its alias changes.

EVERY FIXTURE RESPONSE CARRIES "_fixture": true
    So no one mistakes fabricated data for a working backend, and so the
    frontend can assert on its ABSENCE once the real API is live.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3
import fixtures

_JSON_HEADERS = {"content-type": "application/json"}

# Parameter Store prefix for this environment. Set by Terraform; the fallback
# only matters when running the handler locally.
_SSM_PREFIX = os.environ.get("SSM_PREFIX", "/sportable/staging")

# Values used when Parameter Store cannot be read. They match the committed
# tfvars, so a permission failure degrades to the right answer rather than to
# an error page — but `"source": "fallback"` in the response makes it visible
# instead of silently pretending everything is fine.
_CONFIG_FALLBACK: dict[str, Any] = {
    "distance_bands_m": [250, 500, 1000],
    "default_distance_m": 500,
    "max_results": 100,
}

# Module-level cache. A Lambda execution environment is reused across many
# invocations, so this is read once per COLD START rather than once per request.
# That is the whole reason config in Parameter Store is affordable: a handful of
# API calls per day, not one per user action.
_config_cache: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    """Read search configuration from Parameter Store, once per cold start.

    Returns:
        The configuration, plus a "source" key of "ssm" or "fallback" so the
        caller can tell whether the live values were actually reached.

    Never raises. A configuration read that fails should degrade the answer,
    not take the endpoint down — and the Lambda execution role is managed by
    the account holder, so we cannot guarantee the permission exists.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config: dict[str, Any] = dict(_CONFIG_FALLBACK)
    config["source"] = "fallback"

    try:
        ssm = boto3.client("ssm")
        # One call for the whole subtree. Fetching each parameter individually
        # would multiply the cold-start cost by the number of parameters.
        paginator = ssm.get_paginator("get_parameters_by_path")
        found: dict[str, str] = {}
        for page in paginator.paginate(Path=f"{_SSM_PREFIX}/search", Recursive=True):
            for param in page["Parameters"]:
                found[param["Name"].rsplit("/", 1)[-1]] = param["Value"]

        if found:
            if "distance_bands_m" in found:
                config["distance_bands_m"] = [
                    int(v) for v in found["distance_bands_m"].split(",") if v
                ]
            if "default_distance_m" in found:
                config["default_distance_m"] = int(found["default_distance_m"])
            if "max_results" in found:
                config["max_results"] = int(found["max_results"])
            config["source"] = "ssm"
    except Exception as exc:  # Deliberately broad: see the docstring.
        # Logged, not raised. This line is what tells you the execution role is
        # missing ssm:GetParametersByPath.
        print(f"config: falling back to defaults, could not read {_SSM_PREFIX}: {exc}")

    _config_cache = config
    return config


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build an API Gateway HTTP API v2 response.

    `body` must already be a string — API Gateway does not serialise it for you.
    Returning a dict produces a 502 at runtime while looking correct in tests
    that only inspect the parsed value.
    """
    return {
        "statusCode": status,
        "headers": _JSON_HEADERS,
        "body": json.dumps(body),
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route on the request path.

    Args:
        event: API Gateway HTTP API v2 request. `rawPath` carries the full path
            as the client sent it — CloudFront forwards `/api/v1/...` unchanged.
        context: Lambda context. Unused here; the real handler passes it to AWS
            Lambda Powertools for structured logging.

    Returns:
        An API Gateway HTTP API v2 response.
    """
    path = event.get("rawPath", "/").rstrip("/") or "/"

    if path in ("/api/v1/health", "/health", "/"):
        return _response(200, {"status": "ok", "service": "sportable-api"})

    # Not a fixture. These are the live values the UI must render for AC1.2.4,
    # so the Frontend never hardcodes 250/500/1000 and a change to the bands
    # reaches the interface without a frontend release.
    if path == "/api/v1/config":
        return _response(200, _load_config())

    if path == "/api/v1/sports":
        return _response(200, fixtures.SPORTS)

    if path == "/api/v1/venues/search":
        return _response(200, fixtures.search_response())

    if path.startswith("/api/v1/venues/"):
        venue_id = path.removeprefix("/api/v1/venues/")
        venue = fixtures.venue_response(venue_id)
        if venue is None:
            # A genuine 404 from the API must stay a 404. CloudFront's SPA
            # fallback deliberately does not apply to /api/*, or the frontend
            # would receive HTML where it expected JSON.
            return _response(404, {"error": "venue_not_found", "venue_id": venue_id})
        return _response(200, venue)

    return _response(404, {"error": "route_not_found", "path": path})
