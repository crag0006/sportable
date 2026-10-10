"""The calendar block, time hints, the ids filter and the multi-event file (v0.3 §7.6, §7.7)."""

import re
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import conftest
import pytest
from app.domain.time_hints import hints_for
from fastapi.testclient import TestClient

EVENTS = "/api/v1/events"


# ------------------------------------------------------------------ §7.7.2
def test_hints_read_ranges_singles_and_audiences():
    hints = hints_for(
        "Adults Friday evenings from 6:30 pm to 8:00 pm. Juniors 5:30 pm to 6:30 pm.", ("friday",)
    )
    assert [(h.slot, h.start_local, h.end_local, h.weekdays, h.confidence) for h in hints] == [
        ("adults", "18:30", "20:00", ("friday",), "high"),
        ("juniors", "17:30", "18:30", ("friday",), "high"),
    ]
    assert hints[0].quote.startswith("Adults Friday evenings") and hints[0].basis == "regex"


def test_hints_bind_each_time_to_its_own_day_but_one_time_to_every_day():
    two = hints_for("Fridays 6pm-7:30pm Saturdays 9am-10:30am", ("friday", "saturday"))
    assert [h.weekdays for h in two] == [("friday",), ("saturday",)]
    one = hints_for(
        "We sail on Wednesdays and Fridays from 9:30 am to 1 pm.", ("wednesday", "friday")
    )
    assert [h.weekdays for h in one] == [("wednesday", "friday")]


def test_hints_ignore_prices_durations_and_afternoons():
    assert hints_for("Cost: $10.80 full fee. Duration: 1.75 hours. Saturday afternoons.") == []
    assert hints_for("Mondays 5.30-6.30 for 5-12 year olds")[0].start_local == "17:30"
    single = hints_for("Every Saturday at 8:00 am. Volunteers organise it.")
    assert (single[0].start_local, single[0].end_local, single[0].confidence) == (
        "08:00",
        None,
        "medium",
    )


# ------------------------------------------------------------------ §7.7.1
def test_program_with_a_time_hint_is_a_timed_weekly_entry(client: TestClient):
    cal = client.get(f"{EVENTS}/aaaplay:25089").json()["calendar"]
    assert cal["exportable"] is True and cal["mode"] == "weekly" and "reason" not in cal
    assert cal["weekdays"] == ["wednesday"] and cal["rrule"] == "FREQ=WEEKLY;BYDAY=WE"
    assert cal["time_published"] is False
    assert cal["time_hint"]["start_local"] == "18:30" and cal["time_hint"]["end_local"] == "20:00"
    assert [h["slot"] for h in cal["time_hints"]] == ["main", "juniors"]
    assert cal["description_lines"][0].startswith(
        "Wednesdays, evenings. The publisher's description says:"
    )
    assert "Unknown" not in " ".join(cal["description_lines"])
    assert any(line.startswith("Accessible toilet:") for line in cal["description_lines"])
    assert cal["dedupe_key"] == "sportable:aaaplay:25089"
    assert cal["ics_url"] == "/api/v1/events/aaaplay:25089.ics"
    assert cal["title"] == "Basketball: PlayOn"


def test_google_template_link_carries_the_entry(client: TestClient):
    cal = client.get(f"{EVENTS}/aaaplay:25089").json()["calendar"]
    assert (
        len(cal["google_template_urls"]) == 2
        and cal["google_template_url"] == cal["google_template_urls"][0]
    )
    url = urlparse(cal["google_template_url"])
    assert url.netloc == "calendar.google.com" and url.path == "/calendar/render"
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert q["action"] == "TEMPLATE" and q["text"] == "Basketball: PlayOn"
    assert q["ctz"] == "Australia/Melbourne" and q["recur"] == "RRULE:FREQ=WEEKLY;BYDAY=WE"
    assert q["dates"].endswith("T183000/" + q["dates"][:8] + "T200000") and q["dates"][:8] == cal[
        "first_date"
    ].replace("-", "")
    assert q["location"].startswith("Northcote Aquatic and Recreation Centre")
    assert "Accessible toilet:" in q["details"]
    assert [(link["slot"], link["label"]) for link in cal["google_template_links"]] == [
        ("wednesday", "Wednesday 6:30 pm to 8:00 pm"),
        ("juniors", "Juniors, Wednesday 5:30 pm to 6:30 pm"),
    ]
    assert [link["url"] for link in cal["google_template_links"]] == cal["google_template_urls"]


def test_program_without_a_weekday_is_not_exportable(client: TestClient):
    cal = client.get(f"{EVENTS}/aaaplay:25086").json()["calendar"]
    assert cal["exportable"] is False and cal["reason"] == "no_weekday_published"
    assert cal["message"].startswith("The provider has not published which day this runs")
    assert "google_template_url" not in cal and cal["google_template_urls"] == []
    assert cal["google_template_links"] == []
    assert "first_date" not in cal and "rrule" not in cal


def test_fixture_is_a_single_timed_entry_and_cancelled_is_not_offered(client: TestClient):
    cal = client.get(f"{EVENTS}/fx-1").json()["calendar"]
    assert cal["exportable"] is True and cal["mode"] == "single" and cal["time_published"] is True
    assert cal["start"] and "end" not in cal and "rrule" not in cal
    dates = parse_qs(urlparse(cal["google_template_url"]).query)["dates"][0]
    assert (
        "/" in dates and "Z" not in dates and dates.startswith(cal["start"][:10].replace("-", ""))
    )
    assert "End time is estimated." in cal["description_lines"]
    cancelled = client.get(f"{EVENTS}/fx-cancelled").json()["calendar"]
    assert cancelled["exportable"] is False and cancelled["reason"] == "cancelled"


def test_calendar_block_is_on_the_list_too(client: TestClient):
    body = client.get(EVENTS, params={"sport": "Basketball"}).json()
    assert all("calendar" in e for e in body["events"])


# ------------------------------------------------------------------ §7.7.3
def test_ids_filter_returns_the_requested_order_and_reports_missing(client: TestClient):
    body = client.get(EVENTS, params={"ids": "fx-cancelled,aaaplay:25089,nope"}).json()
    assert [e["id"] for e in body["events"]] == ["fx-cancelled", "aaaplay:25089"]
    assert body["missing"] == ["nope"] and body["filters"]["status"] == "all"
    assert body["page_size"] == 3
    too_many = client.get(EVENTS, params={"ids": ",".join(f"x{i}" for i in range(51))})
    assert too_many.status_code == 422 and too_many.json()["error"]["code"] == "validation_error"


# ------------------------------------------------------------------ §7.6
def test_multi_event_file_has_one_entry_per_slot_with_a_timezone(client: TestClient):
    response = client.get(f"{EVENTS}/calendar.ics", params={"ids": "aaaplay:25089,fx-cancelled"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert 'attachment; filename="sportable-events.ics"' in response.headers["content-disposition"]
    text = response.text.replace("\r\n ", "")
    assert "X-WR-CALNAME:SportAble events" in text and "BEGIN:VTIMEZONE" in text
    assert "UID:aaaplay:25089#wednesday@sportablemelbourne.me" in text
    assert "UID:aaaplay:25089#juniors@sportablemelbourne.me" in text
    assert "DTSTART;TZID=Australia/Melbourne:" in text and "T173000" in text and "T183000" in text
    assert "UID:fx-cancelled@sportablemelbourne.me" in text and "STATUS:CANCELLED" in text
    assert text.count("BEGIN:VEVENT") == 3
    assert "Activity and facility listings from AAA Play" in text


def _uids(client: TestClient, event_id: str) -> list[str]:
    """The UID lines of one event's .ics file, in order."""
    text = client.get(f"{EVENTS}/{event_id}.ics").text.replace("\r\n ", "")
    assert text.count("BEGIN:VEVENT") == text.count("UID:")
    return re.findall(r"UID:(\S+)", text)


def test_two_plain_slots_get_distinct_uids(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Two sentences without an audience word both label their hint ``main``; the UIDs
    must still differ, or a calendar app imports one of the two slots only."""
    base = next(e for e in conftest.EVENTS if e.event_id == "aaaplay:25089")
    weekend = replace(
        base,
        event_id="aaaplay:badminton",
        description="Social badminton. Fridays 7:00 pm to 9:00 pm and Sundays 2:00 pm to 4:00 pm.",
        weekdays=("friday", "sunday"),
    )
    same_day = replace(
        base,
        event_id="aaaplay:twice",
        description="Wednesdays 10:00 am to 11:00 am. A second group runs Wednesdays 6 pm to 7 pm.",
    )
    plain = replace(
        base, event_id="aaaplay:plain", description="Social basketball.", weekdays=("monday",)
    )
    monkeypatch.setattr(conftest, "EVENTS", [*conftest.EVENTS, weekend, same_day, plain])
    assert _uids(client, "aaaplay:badminton") == [
        "aaaplay:badminton#friday@sportablemelbourne.me",
        "aaaplay:badminton#sunday@sportablemelbourne.me",
    ]
    assert _uids(client, "aaaplay:twice") == [
        "aaaplay:twice#wednesday@sportablemelbourne.me",
        "aaaplay:twice#wednesday-2@sportablemelbourne.me",
    ]
    assert _uids(client, "aaaplay:25089") == [
        "aaaplay:25089#wednesday@sportablemelbourne.me",
        "aaaplay:25089#juniors@sportablemelbourne.me",
    ]
    assert _uids(client, "aaaplay:plain") == ["aaaplay:plain@sportablemelbourne.me"]


def _link_labels(client: TestClient, event_id: str) -> list[tuple[str, str]]:
    """``(slot, label)`` of every Google link on the event's calendar block."""
    links = client.get(f"{EVENTS}/{event_id}").json()["calendar"]["google_template_links"]
    return [(link["slot"], link["label"]) for link in links]


def test_google_links_carry_a_label_the_frontend_can_show(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Abinaya's dropdown needs text per slot; the weekday guess moves from the frontend here."""
    base = next(e for e in conftest.EVENTS if e.event_id == "aaaplay:25089")
    weekend = replace(
        base,
        event_id="aaaplay:badminton",
        description="Social badminton. Fridays 7:00 pm to 9:00 pm and Sundays 2:00 pm to 4:00 pm.",
        weekdays=("friday", "sunday"),
    )
    plain = replace(
        base, event_id="aaaplay:plain", description="Social basketball.", weekdays=("monday",)
    )
    open_end = replace(
        base,
        event_id="aaaplay:open",
        description="Every Saturday at 8:00 am.",
        weekdays=("saturday",),
    )
    monkeypatch.setattr(conftest, "EVENTS", [*conftest.EVENTS, weekend, plain, open_end])
    assert _link_labels(client, "aaaplay:badminton") == [
        ("friday", "Friday 7:00 pm to 9:00 pm"),
        ("sunday", "Sunday 2:00 pm to 4:00 pm"),
    ]
    assert _link_labels(client, "aaaplay:plain") == [("monday", "Monday, time not published")]
    assert _link_labels(client, "aaaplay:open") == [("saturday", "Saturday from 8:00 am")]
    fixture = client.get(f"{EVENTS}/fx-1").json()
    assert _link_labels(client, "fx-1") == [
        ("main", f"{fixture['date_local']} {fixture['time_local']}")
    ]


def test_multi_event_file_requires_ids(client: TestClient):
    response = client.get(f"{EVENTS}/calendar.ics")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
