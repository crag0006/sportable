"""Behaviours corrected after the contract v0.3 audit of 10 Oct 2026.

Each test names the contract section it pins. The audit found the code
disagreeing with the contract in these places; the contract was right.
"""

import base64
import json
from datetime import UTC, date, datetime

import handlers.assistant as assistant
from app.domain.events import weekdays_in_window
from app.domain.facilities import present
from app.domain.presenters import register_source_out
from app.repositories.protocols import FacilityRow, SourceRow
from fastapi.testclient import TestClient

SEARCH = "/api/v1/venues/search"


# ------------------------------------------------------------- §2.5 / §10
def test_unknown_path_is_the_error_envelope(client: TestClient):
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["error"]["code"] == "route_not_found"
    assert "/api/v1/nope" in body["error"]["message"]
    assert "detail" not in body


def test_wrong_method_is_the_error_envelope(client: TestClient):
    response = client.post("/api/v1/sports")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_non_integer_distance_is_invalid_distance_band(client: TestClient):
    """§10: any value outside the bands is invalid_distance_band, not a type error."""
    bad = client.get(
        SEARCH, params={"sport": "Basketball", "suburb": "Preston", "distance_m": "abc"}
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "invalid_distance_band"
    fractional = client.get("/api/v1/venues/10432", params={"distance_m": "500.5"})
    assert fractional.json()["error"]["code"] == "invalid_distance_band"
    corridor = client.get(
        "/api/v1/venues/10432/corridor", params={"from": "Preston", "within": "x"}
    )
    assert corridor.json()["error"]["code"] == "invalid_distance_band"


# ------------------------------------------------------------------- §3.5
def test_point_outside_coverage_on_resolve(client: TestClient):
    """A coordinate pair gets the same coverage check as a named place."""
    body = client.get("/api/v1/locations/resolve", params={"q": "-33.87,151.21"}).json()
    assert body["outcome"] == "outside_coverage"
    assert body["matched"]["kind"] == "point"
    assert "coverage" in body
    inside = client.get("/api/v1/locations/resolve", params={"q": "-37.8,144.96"}).json()
    assert inside["outcome"] == "resolved" and inside["matched"]["kind"] == "point"


def test_point_outside_coverage_is_422_on_search_and_venue_page(client: TestClient):
    search = client.get(SEARCH, params={"sport": "Basketball", "near": "-33.87,151.21"})
    assert search.status_code == 422
    assert search.json()["error"]["code"] == "outside_coverage"
    page = client.get("/api/v1/venues/10432", params={"from": "-33.87,151.21"})
    assert page.json()["error"]["code"] == "outside_coverage"
    ok = client.get(SEARCH, params={"sport": "Basketball", "near": "-37.74,145.0"})
    assert ok.status_code == 200


# ------------------------------------------------------------------- §3.6
def _source(rows_loaded: int | None, outcome: str | None) -> SourceRow:
    return SourceRow(
        source_id="DS-02",
        name="National Public Toilet Map",
        publisher=None,
        licence_name=None,
        licence_url=None,
        attribution_text=None,
        landing_page=None,
        publisher_scope=None,
        publisher_last_updated=date(2022, 1, 12),
        retrieved_at=datetime(2026, 9, 1, tzinfo=UTC) if rows_loaded else None,
        rows_loaded=rows_loaded,
        outcome=outcome,
    )


def test_source_status_reflects_the_latest_run_and_the_last_good_one():
    assert register_source_out(_source(3718, "landed"), 365).status == "loaded"
    failed = register_source_out(_source(3718, "failed"), 365)
    assert failed.status == "failed_using_last_good"
    assert failed.row_count == 3718  # the rows in service, not the failed run's
    assert register_source_out(_source(None, "failed"), 365).status == "empty"
    assert register_source_out(_source(None, None), 365).status == "empty"


def test_sources_mode_is_absent_unless_sample(client: TestClient):
    body = client.get("/api/v1/sources").json()
    assert all("mode" not in s for s in body["sources"])


# ------------------------------------------------------------------- §2.2
def test_confirmed_by_proximity_without_a_distance_is_unknown():
    """A spatial row the builder kept no distance for cannot be 'beyond' anything."""
    row = FacilityRow(
        kind="accessible_toilet", status="confirmed", basis="spatial_proximity", distance_m=None
    )
    tile = present(row, "accessible_toilet", 500)
    assert tile.display == "no_published_information"
    assert tile.status == "no_published_information"
    assert tile.distance_m is None
    assert tile.message == "No published information - check with the venue."


# ------------------------------------------------------------------- §5.2
def test_detail_flags_describe_the_emitted_attributes(client: TestClient):
    body = client.get("/api/v1/venues/10432").json()
    tiles = {f["type"]: f for f in body["facilities"]}
    toilet = tiles["accessible_toilet"]["detail"]
    assert (
        toilet["opening_hours"] == "6:00am - 9:00pm" and toilet["opening_hours_unrecorded"] is False
    )
    assert toilet["key_required"] is True and toilet["key_requirement_unrecorded"] is False
    change = tiles["accessible_change_facility"]["detail"]
    assert "opening_hours" not in change and change["opening_hours_unrecorded"] is True
    assert "key_required" not in change and change["key_requirement_unrecorded"] is True


# ------------------------------------------------------------------- §7.3
def test_weekdays_in_window_matches_the_list_rule():
    assert weekdays_in_window(date(2026, 10, 12), date(2026, 10, 14)) == (
        "monday",
        "tuesday",
        "wednesday",
    )
    assert weekdays_in_window(date(2026, 10, 12), date(2026, 10, 18)) is None
    assert weekdays_in_window(date(2026, 10, 12), date(2026, 10, 12)) == ("monday",)


# ------------------------------------------------------------------- §7.6
def test_multi_event_calendar_file_is_its_own_route_not_an_unknown_event(client: TestClient):
    response = client.get("/api/v1/events/calendar.ics")
    assert response.status_code == 422  # the route exists and wants ids; never event_not_found
    assert response.json()["error"]["code"] == "validation_error"


# ------------------------------------------------------------ §8.5 / §11.2
def _call(body: str | None, encoded: bool = False) -> tuple[int, dict]:
    event = {"body": body, "isBase64Encoded": encoded}
    out = assistant.handler(event, None)
    return out["statusCode"], json.loads(out["body"])


def test_assistant_skeleton_rejects_a_body_that_is_not_an_object():
    for body in ("[]", '"hi"', "42", "not json"):
        status, out = _call(body)
        assert status == 400, body
        assert out["error"]["code"] == "invalid_json"


def test_assistant_skeleton_accepts_base64_bodies_and_links_to_the_search_page():
    raw = base64.b64encode(b'{"question": "basketball near Preston"}').decode()
    status, out = _call(raw, encoded=True)
    assert status == 200
    assert out["kind"] == "capability" and out["model_called"] is False
    assert out["links"][0] == {"label": "Search venues", "href": "/venues"}
    status, out = _call("{}")
    assert status == 400 and out["error"]["code"] == "missing_question"
