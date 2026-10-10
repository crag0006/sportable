"""Lambda entry point for the Access Assistant — Epic 6.

    backend/handlers/assistant.py

WHAT IS HERE NOW, AND WHAT IS NOT
    This is the infrastructure skeleton for I3. It implements the two paths
    that need no model call at all:

        AC6.3.1  state the assistant's scope in plain English
        AC6.3.2  refuse an out-of-scope question WITHOUT calling the model

    Intent classification, retrieval and answer composition are app work and
    land in later tasks. Until they do, every question is answered with the
    capability message, which is honest: the assistant genuinely cannot answer
    anything else yet.

WHY THE REFUSAL PATH SHIPS FIRST
    It is the only path that is free. Shipping it on its own means the route,
    the VPC wiring, the throttle and the telemetry can all be proved end to end
    before a single token is billed, and a misconfiguration is found while it
    costs nothing.

WHY THIS SHARES THE API's DEPLOYMENT PACKAGE
    backend/build/package already carries app/ and every dependency. A second
    function pointed at the same archive with a different handler costs one
    line in the build script and keeps the repository layer identical between
    the two. See infra/modules/api/assistant.tf.

NOTHING IS LOGGED FROM THE QUESTION
    AC6.3.5 is a constraint on this file, not a policy note: the default
    instinct of every handler is to log the payload, and an exception handler
    that dumps the request body would break it silently. Counts and categories
    only — see log_event().
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

LOG = logging.getLogger("sportable.assistant")
LOG.setLevel(logging.INFO)

ENVIRONMENT = os.environ.get("ENVIRONMENT", "staging")

# Resolved by Terraform at apply time from SSM, exactly as the API's own
# DATABASE_URL and SEARCH_CONFIG are. Not read from SSM here: this function has
# no route to the SSM API from its subnet and the call would hang.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ASSISTANT_CONFIG = json.loads(os.environ.get("ASSISTANT_CONFIG", "{}"))

CAPABILITY_MESSAGE = (
    "I can help you find sports venues and sporting events in Victoria, and tell you what "
    "has been published about their accessibility — accessible toilets, parking, change "
    "facilities and step-free railway stations nearby. I can also tell you when nobody has "
    "published something, and what to ask the venue instead. I cannot give medical, legal or "
    "safety advice, I cannot promise that a venue or a journey is accessible, and I cannot "
    "take bookings or remember anything you tell me."
)

# SPA routes: the venue search page is /venues; / is the landing page.
SEARCH_LINKS = [
    {"label": "Search venues", "href": "/venues"},
    {"label": "Browse events", "href": "/events"},
]


def log_event(event: str, **fields: Any) -> None:
    """One JSON object per line, counts and categories only.

    Never pass question text, recognised speech, coordinates or anything else a
    person typed. AC6.3.5.
    """
    LOG.info(json.dumps({"event": event, "environment": ENVIRONMENT, **fields}))


def response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    """An API Gateway HTTP API v2 response with a JSON body."""
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _body(event: dict[str, Any]) -> dict[str, Any] | None:
    """The request body as a JSON object, or None when it is not one.

    A base64-encoded body (API Gateway sets ``isBase64Encoded``) is decoded
    first. A body that parses but is not an object (``[]``, ``"hi"``) is
    treated the same as invalid JSON: the handler needs an object.
    """
    import base64
    import binascii

    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """POST /api/v1/assistant

    Returns the capability message for every question, with no model call,
    until intent handling lands. Every failure is the JSON envelope: nothing
    here may fall through to API Gateway's own 500 page.
    """
    try:
        return _answer(event)
    except Exception:
        # Nothing from the body is logged, only that the handler failed.
        log_event("ASSISTANT_ERROR", reason="unhandled")
        return response(
            500,
            {"error": {"code": "internal_error", "message": "Something went wrong on our side."}},
        )


def _answer(event: dict[str, Any]) -> dict[str, Any]:
    """The skeleton's answer: a capability message, or a 400 for a bad body."""
    payload = _body(event)
    if payload is None:
        # The body is not echoed back and not logged — it is the user's words.
        log_event("ASSISTANT_BAD_REQUEST", reason="invalid_json")
        return response(400, {"error": {"code": "invalid_json", "message": "Send a JSON body."}})

    question = payload.get("question")

    if not isinstance(question, str) or not question.strip():
        log_event("ASSISTANT_BAD_REQUEST", reason="missing_question")
        return response(
            400,
            {"error": {"code": "missing_question", "message": "Include a question."}},
        )

    # Length is a category, not content: a count is safe to record and tells us
    # whether speech input is producing very long transcripts.
    log_event(
        "ASSISTANT_REFUSED",
        reason="not_implemented",
        model_called=False,
        question_length=len(question),
    )

    return response(
        200,
        {
            "kind": "capability",
            "answer": CAPABILITY_MESSAGE,
            "model_called": False,
            "links": SEARCH_LINKS,
        },
    )
