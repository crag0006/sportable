"""Tests for the placeholder Lambda handler.

These tests carry more weight than their subject deserves, for two reasons.

First, pytest exits with code 5 — a failure — when it collects no tests at all.
Until real application tests exist, these are what allow the CI pipeline to go
green, and a pipeline that has never been green is a pipeline nobody trusts.

Second, they pin the *response contract* rather than the implementation. The
stub will be deleted, but API Gateway's expectations do not change: an HTTP API
integration needs ``statusCode`` as an integer and ``body`` as an already
serialised string. Asserting that here means the deploy pipeline's smoke test
is checking something that was verified locally first.
"""

import json

from handlers.stub import handler


def test_handler_returns_200():
    """API Gateway treats a missing or non-integer statusCode as a 502."""
    assert handler({}, None)["statusCode"] == 200


def test_handler_returns_json_content_type():
    """The SPA parses the response as JSON; the header has to say so."""
    assert handler({}, None)["headers"]["content-type"] == "application/json"


def test_handler_body_is_a_serialised_string():
    """API Gateway does not serialise the body for you — it must be a string.

    Returning a dict here would produce a 502 at runtime while passing any test
    that only inspected the parsed value, so assert the type explicitly.
    """
    assert isinstance(handler({}, None)["body"], str)


def test_handler_body_reports_ok():
    """The payload the deploy smoke test asserts against."""
    assert json.loads(handler({}, None)["body"]) == {
        "status": "ok",
        "service": "sportable-api",
    }
