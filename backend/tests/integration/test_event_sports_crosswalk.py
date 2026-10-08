"""Event sports resolved through the reviewed crosswalk (data/sql/012).

Skipped unless TEST_DATABASE_URL is set. See conftest.py for how to run them.

One programme per decision the crosswalk makes, because each was wrong before
and each is wrong in a different way:

    Aqua aerobics   narrower       -> Swimming            (was: no match)
    Tennis          split          -> Tennis (Indoor)
                                   -> Tennis (Outdoor)    (was: no match)
    Boccia          added_adaptive -> Boccia              (in no DS-01 venue)
    Art             not_a_sport    -> nothing             (was: offered as a sport)
    Quidditch       unreviewed     -> shown as published  (must not vanish)
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.repositories.protocols import EventFilters

from .conftest import requires_db

WINDOW = {"date_from": date(2020, 1, 1), "date_to": date(2030, 1, 1)}


def titles(repo, *sports: str) -> list[str]:
    filters = EventFilters(now=datetime.now(UTC), sports=tuple(sports), **WINDOW)
    return sorted(event.title for event in repo.list_events(filters))


def sport_names(repo) -> dict[str, int]:
    rows = repo.event_sports(WINDOW["date_from"], WINDOW["date_to"], datetime.now(UTC))
    return {row.name: row.event_count for row in rows}


@requires_db
def test_a_publisher_term_finds_the_venue_sport_it_names(repo) -> None:
    """Aqua aerobics is Swimming. The label match alone found neither."""
    assert titles(repo, "Swimming") == ["Aqua aerobics for beginners"]


@requires_db
def test_a_split_term_answers_both_halves(repo) -> None:
    """The vocabulary has no unqualified Tennis, so one choice would hide the
    other kind of court. This is what a one-to-one alias map could not do."""
    assert titles(repo, "Tennis (Indoor)") == ["Wheelchair tennis social"]
    assert titles(repo, "Tennis (Outdoor)") == ["Wheelchair tennis social"]


@requires_db
def test_a_sport_no_venue_records_is_still_offered(repo) -> None:
    """Boccia is a real sport with no DS-01 venue. It reaches the shared list
    with venue_count 0, because a wheelchair user searching for it should not
    be told it does not exist."""
    assert titles(repo, "Boccia") == ["Boccia club"]

    boccia = next(s for s in repo.list_sports() if s.name == "Boccia")
    assert boccia.venue_count == 0
    assert boccia.event_count == 1


@requires_db
def test_a_term_that_is_not_a_sport_is_not_offered_as_one(repo) -> None:
    """Art is not a sport. The programme still lists; only the sport does not."""
    assert "Art" not in sport_names(repo)
    assert titles(repo, "Art") == []

    listed = titles(repo)
    assert "Art group" in listed, "the programme itself must still be listed"


@requires_db
def test_an_unreviewed_term_keeps_its_published_label(repo) -> None:
    """A term the publisher adds tomorrow has no crosswalk row. It comes
    through as published rather than disappearing, and the events page can
    still filter on it."""
    assert sport_names(repo)["Quidditch"] == 1
    assert titles(repo, "Quidditch") == ["Brand new activity"]


@requires_db
def test_the_shared_sport_list_counts_events_through_the_crosswalk(repo) -> None:
    """The count beside Swimming is the point of the whole exercise: it was
    zero while an Aqua aerobics programme sat in the database."""
    sports = {s.name: s for s in repo.list_sports()}

    assert sports["Swimming"].event_count == 1
    assert sports["Tennis (Indoor)"].event_count == 1
    assert sports["Tennis (Outdoor)"].event_count == 1

    # A venue sport with no programmes still reports zero, not nothing.
    assert sports["Basketball"].event_count == 0
