"""Events endpoints (contract v0.2 section 7) against the in-memory repository."""

from datetime import date, datetime

from app.domain.ics import build_ics, next_weekday
from fastapi.testclient import TestClient

EVENTS = "/api/v1/events"


def test_events_list_shape_and_window(client: TestClient):
    body = client.get(EVENTS).json()
    assert set(body) >= {
        "window",
        "filters",
        "counts",
        "page",
        "page_size",
        "events",
        "attribution",
    }
    assert body["window"]["timezone"] == "Australia/Melbourne"
    assert "Programs are listed" in body["window"]["rule"]
    assert body["counts"]["total"] == 3  # the cancelled fixture is not listable
    assert body["counts"]["fixtures"] == 1 and body["counts"]["programs"] == 2
    assert body["counts"]["unmatched_venue"] == 1
    ids = [e["id"] for e in body["events"]]
    assert ids[0] == "fx-1"  # fixtures first, by start time
    assert "aaaplay:25089" in ids and "aaaplay:25086" in ids
    assert body["attribution"] == [
        "Activity and facility listings from AAA Play, Reclink Australia",
        "Fixture data provided by PlayHQ",
    ]


def test_fixture_row(client: TestClient):
    fx = next(e for e in client.get(EVENTS).json()["events"] if e["id"] == "fx-1")
    assert fx["kind"] == "fixture" and fx["status_label"] == "Scheduled"
    assert fx["starts_at"].endswith("+10:00")
    assert fx["date_local"] and fx["time_local"] == "19:30"
    assert "recurrence" not in fx
    assert fx["venue"]["matched"] is True and fx["venue"]["href"] == "/venues/10432"
    assert fx["links"]["directions"] == "/venues/10432/directions"
    assert fx["links"]["ics"] == "/api/v1/events/fx-1.ics"
    assert [f["type"] for f in fx["access"]["facilities"]] == [
        "accessible_toilet",
        "accessible_parking",
        "accessible_transport_stop",
        "accessible_change_facility",
    ]
    assert fx["access"]["facilities"][0]["display"] == "nearby"  # same tile as the venue page
    assert fx["access"]["summary"].startswith("Accessible toilet 45 m away.")
    assert fx["source"]["attribution"] == "Fixture data provided by PlayHQ"


def test_program_row_and_unmatched_venue(client: TestClient):
    events = {e["id"]: e for e in client.get(EVENTS).json()["events"]}
    playon = events["aaaplay:25089"]
    assert playon["kind"] == "program" and playon["status_label"] == "Runs weekly"
    assert "starts_at" not in playon
    assert playon["recurrence"] == {
        "weekdays": ["wednesday"],
        "time_of_day": ["evening"],
        "days_stated": True,
        "summary": "Wednesdays, evenings",
    }
    assert playon["access_needs"] == []  # empty tag is no published information
    pedal = events["aaaplay:25086"]
    assert pedal["recurrence"]["days_stated"] is False
    assert pedal["venue"]["matched"] is False
    assert "not in our venue list" in pedal["venue"]["message"]
    assert "venue" not in pedal["links"] and "directions" not in pedal["links"]
    assert all(f["display"] == "no_published_information" for f in pedal["access"]["facilities"])
    assert pedal["access"]["summary"].startswith("No published information for")


def test_facilities_group_but_never_hide(client: TestClient):
    body = client.get(EVENTS, params={"facilities": "accessible_toilet"}).json()
    assert body["filters"]["facilities_requested"] == ["accessible_toilet"]
    assert [e["id"] for e in body["events"]] == ["fx-1", "aaaplay:25089"]
    assert [e["id"] for e in body["undocumented_group"]["events"]] == ["aaaplay:25086"]
    assert body["not_available_group"]["count"] == 0
    assert body["counts"]["matched"] == 2 and body["counts"]["undocumented"] == 1
    assert body["events"][0]["access"]["requested_met"] is True
    assert body["undocumented_group"]["events"][0]["access"]["requested_met"] is False


def test_status_all_includes_cancelled(client: TestClient):
    body = client.get(EVENTS, params={"status": "all"}).json()
    assert "fx-cancelled" in [e["id"] for e in body["events"]]
    cancelled = client.get(f"{EVENTS}/fx-cancelled").json()
    assert cancelled["status_label"] == "Cancelled"  # a shared link still resolves


def test_window_validation(client: TestClient):
    assert client.get(EVENTS, params={"from": "2026-09-20", "to": "2026-09-10"}).status_code == 422
    assert (
        client.get(EVENTS, params={"from": "2026-09-01", "to": "2026-12-31"}).json()["error"][
            "code"
        ]
        == "invalid_date_range"
    )
    assert client.get(EVENTS, params={"from": "yesterday"}).status_code == 422


def test_short_window_selects_programs_by_weekday(client: TestClient):
    # A Monday-only window: the Wednesday program drops out, the undated one stays.
    body = client.get(EVENTS, params={"from": "2026-09-21", "to": "2026-09-21"}).json()
    ids = [e["id"] for e in body["events"]]
    assert "aaaplay:25089" not in ids and "aaaplay:25086" in ids


def test_counts_by_date_expands_programs(client: TestClient):
    body = client.get(EVENTS, params={"from": "2026-09-14", "to": "2026-09-27"}).json()
    by_date = body["counts"]["by_date"]
    assert by_date.get("2026-09-16") == 1 and by_date.get("2026-09-23") == 1  # Wednesdays


def test_empty_message_names_all_three_remedies(client: TestClient):
    body = client.get(EVENTS, params={"sport": "Curling"}).json()
    assert body["events"] == []
    assert body["empty_message"] == (
        "No Curling events found between 2026-09-14 and 2026-10-12. "
        "Try a wider date range, remove a filter, or try a nearby suburb."
    )


def test_events_near_a_place_carry_distance(client: TestClient):
    body = client.get(EVENTS, params={"suburb": "Preston"}).json()
    assert body["reference_point"]["label"] == "the centre of Preston"
    assert body["filters"]["within_m"] == 10000
    fx = next(e for e in body["events"] if e["id"] == "fx-1")
    assert fx["distance_m"] == 640


def test_event_sports(client: TestClient):
    body = client.get(f"{EVENTS}/sports").json()
    assert body["sports"][0] == {"name": "Basketball", "event_count": 2}


def test_event_detail_and_share(client: TestClient):
    body = client.get(f"{EVENTS}/fx-1").json()
    assert body["share"]["url"].endswith("/events/fx-1")
    assert body["venue_card"]["id"] == "10432"
    assert body["venue_card"]["upcoming_events"]["count"] == 1
    assert client.get(f"{EVENTS}/nope").json()["error"]["code"] == "event_not_found"


def test_venue_card_counts_upcoming_events(client: TestClient):
    body = client.get("/api/v1/venues/11876").json()
    assert body["upcoming_events"] == {"count": 1, "href": "/events?venue_id=11876"}


def test_ics_for_a_fixture(client: TestClient):
    response = client.get(f"{EVENTS}/fx-1.ics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert 'filename="sportable-fx-1.ics"' in response.headers["content-disposition"]
    text = response.text
    assert "BEGIN:VEVENT" in text and "UID:fx-1@sportablemelbourne.me" in text
    assert "SUMMARY:Basketball: Preston Bullets v Northcote Giants" in text
    assert "DTSTART:" in text and "DTEND:" in text
    assert "LOCATION:Preston City Oval\\, 121 Cramer Street\\, Preston VIC 3072" in text
    assert "STATUS:CONFIRMED" in text
    assert "End time is estimated." in text.replace("\r\n ", "")


def test_ics_for_a_program_is_a_weekly_rule(client: TestClient):
    text = client.get(f"{EVENTS}/aaaplay:25089.ics").text
    assert "RRULE:FREQ=WEEKLY;BYDAY=WE" in text
    assert "DTSTART;VALUE=DATE:" in text
    assert "Wednesdays\\, evenings" in text


def test_ics_builder_folds_long_lines_and_escapes():
    text = build_ics(
        uid="x@test",
        summary="A; b, c",
        description="line one\nline two " + "x" * 120,
        location=None,
        url="https://example.test/events/x",
        status="CONFIRMED",
        starts_at=datetime(2026, 9, 26, 9, 30, tzinfo=datetime.now().astimezone().tzinfo),
        ends_at=None,
        weekdays=(),
        timezone="Australia/Melbourne",
        latitude=None,
        longitude=None,
        now=datetime(2026, 9, 14, 0, 0),
    )
    assert "SUMMARY:A\\; b\\, c" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    assert next_weekday(date(2026, 9, 14), "wednesday") == date(2026, 9, 16)
