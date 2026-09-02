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

import fixtures

_JSON_HEADERS = {"content-type": "application/json"}

# Search configuration, resolved by Terraform at apply time and passed in as one
# JSON blob. See the data source in infra/modules/api/main.tf for why it is not
# read from Parameter Store at runtime.
#
# THE SHORT VERSION: this function runs in a private subnet with no route to the
# internet. An SDK call to Parameter Store does not fail there, it HANGS, until
# the 10 s function timeout turns the whole request into a 500. Reaching SSM
# from inside the VPC needs an interface endpoint at roughly USD $7.30/month,
# which is more than this project's entire budget target.
#
# So the handler makes no network call of its own. Parsing an environment
# variable cannot time out.
_CONFIG_ENV = "SEARCH_CONFIG"

# Used when the environment variable is absent or unparseable — running the
# handler locally, or a deploy that predates this variable. These match the
# committed tfvars, so the degraded answer is still the right answer.
_CONFIG_FALLBACK: dict[str, Any] = {
    "distance_bands_m": [250, 500, 1000],
    "default_distance_m": 500,
    "max_results": 100,
}

# Parsed once per cold start rather than per request. Cheap either way now, but
# it keeps the response object from being rebuilt on every invocation.
_config_cache: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    """Return search configuration, with a "source" of "terraform" or "fallback".

    Never raises. A configuration problem should degrade the answer, not take
    the endpoint down — and "source" makes the degradation visible rather than
    letting the handler quietly pretend the values are live.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config: dict[str, Any] = dict(_CONFIG_FALLBACK)
    config["source"] = "fallback"

    raw = os.environ.get(_CONFIG_ENV)
    if raw:
        try:
            # Parameter Store returns every value as a string, including the
            # StringList, so each one is converted explicitly here rather than
            # trusted to arrive as the right type.
            parsed = json.loads(raw)
            if "distance_bands_m" in parsed:
                config["distance_bands_m"] = [
                    int(v) for v in str(parsed["distance_bands_m"]).split(",") if v
                ]
            if "default_distance_m" in parsed:
                config["default_distance_m"] = int(parsed["default_distance_m"])
            if "max_results" in parsed:
                config["max_results"] = int(parsed["max_results"])
            config["source"] = "terraform"
        except (ValueError, TypeError) as exc:
            print(f"config: {_CONFIG_ENV} present but unusable, using defaults: {exc}")

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
