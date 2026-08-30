"""Tests for the placeholder handler and its draft fixtures.

These carry more weight than their subject deserves, for two reasons.

First, pytest exits with code 5 — a failure — when it collects no tests. Until
real application tests exist, these are what let CI go green.

Second, they pin the RESPONSE CONTRACT rather than the implementation. The stub
will be deleted; API Gateway's expectations will not change, and neither will
the product rules the fixtures encode.
"""

import json

import fixtures
from handlers.stub import handler


def _call(path: str) -> dict:
    return handler({"rawPath": path}, None)


def _body(path: str) -> dict:
    return json.loads(_call(path)["body"])


# ---------------------------------------------------------------- API Gateway
def test_health_returns_200():
    """API Gateway treats a missing or non-integer statusCode as a 502."""
    assert _call("/api/v1/health")["statusCode"] == 200


def test_body_is_a_serialised_string():
    """API Gateway does not serialise the body for you.

    Returning a dict produces a 502 at runtime while passing any test that only
    inspects the parsed value, so assert the type explicitly.
    """
    assert isinstance(_call("/api/v1/health")["body"], str)


def test_unknown_route_is_404():
    """A genuine 404 from the API must stay a 404.

    CloudFront's SPA fallback maps 403/404 to index.html with status 200, but
    deliberately NOT for /api/*, or the frontend would receive HTML where it
    expected JSON.
    """
    assert _call("/api/v1/nope")["statusCode"] == 404


def test_trailing_slash_is_tolerated():
    assert _call("/api/v1/sports/")["statusCode"] == 200


# ------------------------------------------------------------- product rules
def test_no_facility_uses_a_boolean():
    """ "Unknown is never a no."

    Status is a three-state string, never a boolean. A boolean would make
    `if facility["confirmed"]` render an undocumented facility as absent, which
    is the single failure mode the product is designed to avoid (AC1.3.3).
    """
    for venue in _body("/api/v1/venues/search")["results"]:
        for facility in venue["facilities"]:
            assert isinstance(facility["status"], str)
            assert facility["status"] in {
                fixtures.STATUS_CONFIRMED,
                fixtures.STATUS_NOT_AVAILABLE,
                fixtures.STATUS_NO_PUBLISHED_INFORMATION,
            }


def test_confirmed_facilities_always_carry_provenance():
    """AC1.3.2 — distance, source name and the date the source was updated."""
    for venue in _body("/api/v1/venues/search")["results"]:
        for facility in venue["facilities"]:
            if facility["status"] == fixtures.STATUS_CONFIRMED:
                assert isinstance(facility["distance_m"], int)
                assert facility["source"]["name"]
                assert facility["source"]["last_updated"]


def test_undocumented_venues_are_grouped_not_removed():
    """AC1.2.3 — grouped and counted, never silently dropped."""
    body = _body("/api/v1/venues/search")
    group = body["undocumented_group"]
    assert group["count"] == len(group["results"])
    assert group["count"] > 0
    assert group["label"]


def test_reference_point_is_named():
    """AC1.1.3 — a suburb is an area, not a point, so the origin must be stated."""
    assert _body("/api/v1/venues/search")["reference_point"]["label"]


def test_no_combined_accessibility_score_anywhere():
    """AC2.1.2 — no score, rating, percentage or star value, on any endpoint.

    A single number hides the one failed facility that decides whether a person
    can attend.
    """
    forbidden = ("score", "rating", "percentage", "stars", "overall")
    for path in ("/api/v1/venues/search", "/api/v1/venues/vsr-10432"):
        raw = json.dumps(_body(path)).lower()
        for word in forbidden:
            assert word not in raw, f"{word!r} appears in {path}"


# --------------------------------------------------------------- venue card
def test_venue_card_states_what_it_cannot_tell_you():
    """AC2.1.5 — a headed section naming the gaps, with a plain-English reason."""
    limits = _body("/api/v1/venues/vsr-10432")["limits"]
    assert limits["heading"]
    assert len(limits["items"]) >= 1
    assert all(item["reason"] for item in limits["items"])


def test_missing_venue_returns_404():
    assert _call("/api/v1/venues/does-not-exist")["statusCode"] == 404


def test_every_response_is_marked_as_a_fixture():
    """So nobody mistakes fabricated data for a working backend."""
    for path in ("/api/v1/venues/search", "/api/v1/venues/vsr-10432"):
        assert _body(path)["_fixture"] is True


# -------------------------------------------------------------------- config
# /api/v1/config is not a fixture. It carries the live values the interface
# renders for AC1.2.4, so these tests pin the shape the Frontend depends on.
def test_config_returns_200():
    assert _call("/api/v1/config")["statusCode"] == 200


def test_config_carries_the_three_bands_ac124():
    """AC1.2.4 — the user chooses 250 m, 500 m or 1 km."""
    assert _body("/api/v1/config")["distance_bands_m"] == [250, 500, 1000]


def test_config_default_is_one_of_the_offered_bands():
    """A default outside the bands shows a result set no click can reproduce.

    Terraform enforces this too, as a precondition on the SSM parameter. Both
    guards are cheap and they fail at different times — this one at test time,
    that one at plan time.
    """
    body = _body("/api/v1/config")
    assert body["default_distance_m"] in body["distance_bands_m"]


def test_config_degrades_to_defaults_without_aws():
    """No credentials in CI, so this exercises the fallback path.

    The endpoint must answer rather than raise: the Lambda execution role is
    managed by the account holder and we cannot guarantee it can read SSM. A
    config read that fails should degrade the answer, not take the API down.

    `source` is what makes the degradation visible instead of silent — if this
    ever reads "ssm" in CI, something is reaching AWS that should not be.
    """
    assert _body("/api/v1/config")["source"] == "fallback"


def test_config_is_not_marked_as_a_fixture():
    """Fixtures carry _fixture: true. Real config must not, or the Frontend's
    check for fabricated data would flag it once the real API lands."""
    assert "_fixture" not in _body("/api/v1/config")
