"""The Read Aloud payload (US3.3): short, ordered, and never silently short of a facility."""

from datetime import UTC, date, datetime

import pytest
from app.domain.facilities import KIND_LABELS, KINDS
from app.domain.presenters import venue_card_out
from app.domain.summary import (
    SUMMARY_WORD_CAP,
    _apply_cap,
    _Sentence,
)
from app.repositories.protocols import FacilityRow, SportEntry, VenueRow
from fastapi.testclient import TestClient

RETRIEVED = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)
DS01 = "Sport and Recreational Facilities List"
DS02 = "National Public Toilet Map"


def _row(
    kind: str, status: str, basis: str, distance_m: float | None, **extra: object
) -> FacilityRow:
    fields: dict[str, object] = {
        "source_name": DS02,
        "source_updated": date(2026, 7, 14),
        "retrieved_at": RETRIEVED,
    }
    fields.update(extra)
    return FacilityRow(
        kind=kind,
        status=status,
        basis=basis,
        distance_m=distance_m,
        **fields,  # type: ignore[arg-type]
    )


def _venue(*facilities: FacilityRow, **overrides: object) -> VenueRow:
    fields: dict[str, object] = {
        "venue_id": "10432",
        "name": "Preston City Oval",
        "suburb": "Preston",
        "postcode": "3072",
        "lga": "Darebin",
        "address": "121 Cramer Street, Preston VIC 3072",
        "latitude": -37.7401,
        "longitude": 145.0093,
        "distance_m": None,
        "sports": (SportEntry("Basketball", None),),
        "facilities": facilities,
        "retrieved_at": RETRIEVED,
    }
    fields.update(overrides)
    return VenueRow(**fields)  # type: ignore[arg-type]


def _sentences(venue: VenueRow, limit_m: int = 500) -> list[str]:
    return venue_card_out(venue, None, limit_m).summary_sentences


def _sentence_for(sentences: list[str], kind: str) -> str:
    prefix = f"{KIND_LABELS[kind]}:"
    found = [s for s in sentences if s.startswith(prefix)]
    assert len(found) == 1, f"expected exactly one sentence for {kind}, got {found}"
    return found[0]


# ------------------------------------------------ the rule that matters
@pytest.mark.parametrize("kind", KINDS)
def test_no_facility_can_be_missing_from_the_summary(kind: str):
    """AC4.2.3 in the audio channel.

    A facility left out of the spoken summary is heard as a facility that is
    not there, and the listener has no label to check it against. Every kind
    gets a sentence whatever the venue rows happen to contain — here, a venue
    the pipeline wrote nothing at all for.
    """
    sentences = _sentences(_venue())
    assert _sentence_for(sentences, kind)


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_is_spoken_as_unknown(kind: str):
    """Never "not available", never silence. The exact words matter here."""
    sentence = _sentence_for(_sentences(_venue()), kind)
    assert sentence == f"{KIND_LABELS[kind]}: no published information."
    assert "not available" not in sentence


def test_a_recorded_absence_is_not_spoken_as_unknown():
    """The other half of the same rule: a published "no" is a different sentence."""
    sentences = _sentences(
        _venue(_row("accessible_toilet", "not_available", "publisher_attribute", None))
    )
    toilet = _sentence_for(sentences, "accessible_toilet")
    assert "not available" in toilet
    assert "no published information" not in toilet


def test_all_four_appear_in_the_contract_order():
    order = [
        sentences.index(_sentence_for(sentences, kind))
        for kind in KINDS
        for sentences in [_sentences(_venue())]
    ]
    assert order == sorted(order)


# --------------------------------------------------------------- basis
def test_the_venues_own_record_and_a_nearby_facility_are_told_apart():
    """The venue's own record and a nearby public facility are different
    claims, and are spoken as different claims, with the source named."""
    sentences = _sentences(
        _venue(
            _row(
                "accessible_parking",
                "confirmed",
                "publisher_attribute",
                None,
                source_name=DS01,
            ),
            _row("accessible_toilet", "confirmed", "spatial_proximity", 45.0),
        )
    )
    parking = _sentence_for(sentences, "accessible_parking")
    toilet = _sentence_for(sentences, "accessible_toilet")
    assert "at the venue" in parking and DS01 in parking
    assert "45 metres away" in toilet and "nearest mapped facility" in toilet
    assert DS02 in toilet


def test_beyond_the_chosen_band_says_which_band():
    sentences = _sentences(
        _venue(
            _row(
                "accessible_change_facility",
                "no_published_information",
                "spatial_proximity",
                1340.0,
            )
        ),
        limit_m=500,
    )
    change = _sentence_for(sentences, "accessible_change_facility")
    assert "1340 metres away" in change and "beyond your 500 metre limit" in change


# ----------------------------------------------------- shape and length
def test_each_element_is_exactly_one_sentence():
    """AC3.3.3 - the frontend highlights an element, so an element is a sentence.

    Handing over two sentences in one element, or half of one, is what makes
    the highlight drift.
    """
    for sentence in _sentences(
        _venue(_row("accessible_toilet", "confirmed", "spatial_proximity", 45.0))
    ):
        assert sentence.strip() == sentence and sentence
        assert sentence.endswith(".")
        assert ". " not in sentence, f"more than one sentence in one element: {sentence!r}"


def test_the_summary_fits_inside_about_a_minute():
    sentences = _sentences(
        _venue(*(_row(kind, "confirmed", "spatial_proximity", 45.0) for kind in KINDS))
    )
    assert sum(len(s.split()) for s in sentences) <= SUMMARY_WORD_CAP


def test_the_cap_drops_optional_sentences_and_never_a_facility():
    required = [_Sentence(f"{KIND_LABELS[kind]}: no published information.") for kind in KINDS]
    optional = [_Sentence("A long optional aside worth several words indeed.", required=False)]
    kept = _apply_cap([*required, *optional], cap=5)
    assert kept == [s.text for s in required]


def test_the_cap_keeps_required_sentences_even_when_they_overrun():
    """A summary that fits by omitting a toilet is not shorter, it is wrong."""
    required = [_Sentence(f"{KIND_LABELS[kind]}: no published information.") for kind in KINDS]
    assert _apply_cap(required, cap=1) == [s.text for s in required]


# ------------------------------------------------------ through the API
def test_venue_page_carries_the_summary(client: TestClient):
    body = client.get("/api/v1/venues/10432").json()
    sentences = body["summary_sentences"]
    assert sentences[0].startswith("Preston City Oval is a sports venue in Preston")
    for kind in KINDS:
        assert _sentence_for(sentences, kind)
    assert sum(len(s.split()) for s in sentences) <= SUMMARY_WORD_CAP


def test_event_page_carries_the_summary(client: TestClient):
    body = client.get("/api/v1/events/fx-1").json()
    sentences = body["summary_sentences"]
    assert sentences[0].startswith("Preston Bullets v Northcote Giants is a basketball fixture")
    # Where, then the four facilities, then when it runs.
    assert any("It is at Preston City Oval" in s for s in sentences)
    assert any(s.startswith("It starts on ") for s in sentences)
    for kind in KINDS:
        assert _sentence_for(sentences, kind)
    assert sum(len(s.split()) for s in sentences) <= SUMMARY_WORD_CAP


def test_a_program_summary_says_when_it_runs(client: TestClient):
    sentences = client.get("/api/v1/events/aaaplay:25089").json()["summary_sentences"]
    assert "It runs on Wednesdays, evenings." in sentences


def test_an_unmatched_venue_speaks_four_unknowns_and_says_why(client: TestClient):
    """AC5.2.2. The listener is told the venue is not in our list BEFORE the
    four unknowns, so they hear a reason rather than an outage."""
    sentences = client.get("/api/v1/events/aaaplay:25086").json()["summary_sentences"]
    reason = next(i for i, s in enumerate(sentences) if "not in our venue list" in s)
    for kind in KINDS:
        sentence = _sentence_for(sentences, kind)
        assert sentence.endswith("no published information.")
        assert sentences.index(sentence) > reason


def test_a_cancelled_event_says_so_early(client: TestClient):
    sentences = client.get("/api/v1/events/fx-cancelled").json()["summary_sentences"]
    assert sentences[1] == "This event is cancelled."


def test_every_api_sentence_is_a_single_sentence(client: TestClient):
    for url in ("/api/v1/venues/10432", "/api/v1/events/fx-1", "/api/v1/events/aaaplay:25086"):
        for sentence in client.get(url).json()["summary_sentences"]:
            assert sentence.endswith(".") and ". " not in sentence, (url, sentence)


def test_summary_is_not_on_every_list_row(client: TestClient):
    """AC3.3.1 is about a page. Fifty rows of unspoken summary is payload."""
    body = client.get("/api/v1/events").json()
    assert all("summary_sentences" not in event for event in body["events"])
