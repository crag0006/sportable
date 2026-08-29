"""Placeholder Lambda handler for the SportAble API.

WHY THIS FILE EXISTS
    T2 wires API Gateway to a Lambda function. That Terraform needs *some*
    deployable handler to point at, and the real FastAPI application is being
    written by the backend engineer in parallel. Without this file the
    infrastructure work would sit blocked behind application work — which is
    exactly the dependency this project is structured to avoid.

    It also gives CI something real to execute: pytest exits with code 5 when it
    collects no tests, so the pipeline cannot go green against an empty
    ``tests/`` directory.

HOW IT GETS REPLACED
    One line of Terraform. The Lambda's ``handler`` argument changes from
    ``handlers.stub.handler`` to the Mangum adapter wrapping the FastAPI app
    (``handlers.api.handler``). Nothing else about the function, its role, its
    VPC attachment or its alias changes.

THE RESPONSE SHAPE
    API Gateway *HTTP APIs* (payload format 2.0) accept either a plain object,
    which is serialised as the whole response body, or the explicit structure
    returned here. The explicit form is used deliberately: it is the same shape
    the real handler will return, so the API Gateway integration, the CORS
    configuration and the deploy smoke test are all exercised against a
    realistic response rather than one that happens to work by default.
"""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Return a static health payload.

    Args:
        event: The API Gateway HTTP API v2 request. Ignored — this handler
            responds identically to every request, including the deploy
            pipeline's smoke test against ``/api/v1/health``.
        context: The Lambda context object (request id, remaining time, memory
            limit). Ignored here; the real handler passes it to AWS Lambda
            Powertools for structured logging and tracing.

    Returns:
        An API Gateway HTTP API v2 response: status code, headers, and a body
        that must already be a string — API Gateway does not serialise it for
        you.
    """
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": '{"status":"ok","service":"sportable-api"}',
    }


x   =    1
