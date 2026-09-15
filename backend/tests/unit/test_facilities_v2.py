"""Contract v0.2 §2.2 - three statuses, six presentations, one sentence each."""

from datetime import date, datetime

import pytest
from app.domain.facilities import (
    KINDS,
    Presentation,
    display,
    effective_status,
    group,
    message,
    parse_kinds,
    present,
    presentations_for,
)
from app.domain.provenance import is_stale, source_ref
from app.repositories.protocols import FacilityRow, VenueRow

DS01 = "Sport and Recreational Facilities List"
DS02 = "National Public Toilet Map"


def _row(status: str, basis: str, distance_m: float | None, **extra: object) -> FacilityRow:
    return FacilityRow(
        kind="accessible_toilet",
        status=status,
        basis=basis,
        distance_m=distance_m,
        source_name=DS02 if basis == "spatial_proximity" else DS01,
        **extra,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- display
def test_publisher_confirmed_is_at_the_venue_even_with_a_kept_distance():
    row = _row("confirmed", "publisher_attribute", 298.0)
    assert display(row, 250) == "at_venue"
    assert message(row, "accessible_toilet", 250) == f"At the venue, per {DS01}."


def test_inside_venue_amenity_is_at_the_venue():
    row = _row("confirmed", "spatial_proximity", 12.0, is_inside_venue=True)
    assert display(row, 250) == "at_venue"


def test_nearby_within_the_band_uses_the_band_flags_when_present():
    row = _row("confirmed", "spatial_proximity", 130.0, within_250m=True, within_500m=True)
    assert display(row, 250) == "nearby"
    assert message(row, "accessible_toilet", 250) == (
        "Public accessible toilet 130 m away (straight line)."
    )


def test_confirmed_beyond_the_chosen_band_is_not_confirmed_at_that_band():
    """Data Layer guide §4.1: status is evaluated at 1 km; the API re-evaluates
    it at the band the person chose. 900 m is not a yes to someone who chose 250."""
    row = _row("confirmed", "spatial_proximity", 900.0, within_250m=False, within_500m=False)
    assert display(row, 250) == "beyond_limit"
    assert effective_status(row, 250) == "no_published_information"
    assert display(row, 1000) == "nearby"
    assert effective_status(row, 1000) == "confirmed"


def test_beyond_limit_falls_back_to_arithmetic_without_flags():
    row = _row("confirmed", "spatial_proximity", 600.0)
    assert display(row, 500) == "beyond_limit"
    assert message(row, "accessible_toilet", 500) == (
        "Nearest recorded accessible toilet is 600 m away, beyond your 500 m limit."
    )


def test_unpublished_with_a_far_distance_shows_the_distance_not_the_sentence():
    row = _row("no_published_information", "spatial_proximity", 1340.0)
    assert display(row, 1000) == "beyond_limit"
    assert "1340 m" in message(row, "accessible_toilet", 1000)


def test_not_available_without_alternative():
    row = _row("not_available", "publisher_attribute", None)
    assert display(row, 500) == "not_available"
    assert message(row, "accessible_toilet", 500) == f"Not available, per {DS01}."


def test_not_available_with_alternative_offers_it_without_changing_the_status():
    row = _row("not_available", "publisher_attribute", None, alternative_distance_m=158.0)
    assert display(row, 500) == "not_available_alternative"
    assert effective_status(row, 500) == "not_available"
    assert message(row, "accessible_toilet", 500) == (
        "Not at this venue. Nearest public accessible toilet 158 m away."
    )


def test_nothing_published_is_never_a_no():
    row = _row("no_published_information", "not_published", None)
    assert display(row, 500) == "no_published_information"
    assert display(None, 500) == "no_published_information"
    assert message(None, "accessible_toilet", 500) == (
        "No published information - check with the venue."
    )


def test_transport_is_labelled_as_a_railway_station():
    shown = present(None, "accessible_transport_stop", 500)
    assert shown.label == "Step-free railway station"
    assert shown.basis == "not_published"


def test_presentations_always_cover_the_four_kinds_in_order(venues: list[VenueRow]):
    tiles = presentations_for(venues[0], 500)
    assert [t.kind for t in tiles] == list(KINDS)
    assert all(isinstance(t, Presentation) for t in tiles)


# ------------------------------------------------------------------ group
def test_group_lists_all_three_groups(venues: list[VenueRow]):
    groups = group(venues, ["accessible_toilet", "accessible_change_facility"], 500)
    assert [v.venue_id for v in groups.matched] == ["11876"]
    assert [v.venue_id for v in groups.undocumented] == ["10432"]
    # v0.1 only counted these; v0.2 lists them so the alternative can be shown.
    assert [v.venue_id for v in groups.not_available] == ["10088"]


def test_group_without_kinds_matches_everything(venues: list[VenueRow]):
    groups = group(venues, [], 500)
    assert len(groups.matched) == 3
    assert groups.undocumented == [] and groups.not_available == []


def test_parse_kinds_returns_database_names():
    assert parse_kinds(["toilet,accessible_parking", "stop"]) == [
        "accessible_toilet",
        "accessible_parking",
        "accessible_transport_stop",
    ]


# ------------------------------------------------------------- provenance
@pytest.mark.parametrize(
    ("updated", "threshold", "stale"),
    [
        (date(2026, 1, 1), 365, False),
        (date(2025, 1, 1), 365, True),
        (None, 365, True),
    ],
)
def test_is_stale(updated: date | None, threshold: int, stale: bool):
    assert is_stale(updated, threshold, today=date(2026, 9, 14)) is stale


def test_source_ref_applies_the_register_threshold_before_the_default():
    ref = source_ref(
        DS02,
        source_id="DS-02",
        publisher_last_updated=date(2022, 1, 12),
        retrieved_at=datetime(2026, 9, 1, 2, 0),
        stale_after_days=30,
        default_stale_after_days=365,
        today=date(2026, 9, 14),
    )
    assert ref is not None
    assert ref.stale_after_days == 30
    assert ref.possibly_out_of_date is True
    assert ref.retrieved_at == date(2026, 9, 1)


def test_source_ref_is_none_without_a_source():
    assert source_ref(None) is None
