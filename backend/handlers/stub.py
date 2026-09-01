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
from typing import Any

import fixtures

_JSON_HEADERS = {"content-type": "application/json"}


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
