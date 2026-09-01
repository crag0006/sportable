"""The translation from database vocabulary to interface vocabulary."""

import pytest
from app.domain.facilities import AmenityView, classify, parse_needs, partition, to_view
from app.repositories.protocols import FacilityRow, VenueRow


def _row(status: str, basis: str, distance_m: float | None) -> FacilityRow:
    return FacilityRow(kind="accessible_toilet", status=status, basis=basis, distance_m=distance_m)


# ---------------------------------------------------------------- to_view
def test_confirmed_at_the_venue_has_no_distance():
    assert to_view(_row("confirmed", "publisher_attribute", None)) == AmenityView("confirmed")


def test_publisher_confirmed_stays_at_the_venue_even_with_a_nearby_distance():
    """The status builder keeps the nearest public amenity's distance on a row
    the venue's own record already confirms. That distance is another
    facility's; it must not turn "at the venue" into "298 m away"."""
    assert to_view(_row("confirmed", "publisher_attribute", 298.0)) == AmenityView("confirmed")


def test_confirmed_nearby_is_recorded_with_metres():
    assert to_view(_row("confirmed", "spatial_proximity", 45.4)) == AmenityView("recorded", 45)


def test_beyond_one_km_keeps_its_distance_and_is_recorded():
    """The Data team's second edge case: distance + no_published_information.

    A published toilet 1.3 km away is published. It must never be rendered with
    the "no published information" sentence — the UI compares the distance with
    the selected band and says "beyond your limit".
    """
    view = to_view(_row("no_published_information", "spatial_proximity", 1340.0))
    assert view == AmenityView("recorded", 1340)


def test_not_available_is_absent():
    assert to_view(_row("not_available", "publisher_attribute", None)) == AmenityView("absent")


def test_nothing_published_is_none_and_never_a_no():
    assert to_view(_row("no_published_information", "not_published", None)) == AmenityView("none")
    assert to_view(None) == AmenityView("none")


# ---------------------------------------------------------------- classify
@pytest.mark.parametrize(
    ("view", "limit", "verdict"),
    [
        (AmenityView("confirmed"), 250, "pass"),
        (AmenityView("recorded", 200), 250, "pass"),
        (AmenityView("recorded", 250), 250, "pass"),
        (AmenityView("recorded", 251), 250, "open"),
        (AmenityView("recorded", 1340), 1000, "open"),
        (AmenityView("none"), 1000, "open"),
        (AmenityView("absent"), 1000, "fail"),
    ],
)
def test_classify(view: AmenityView, limit: int, verdict: str):
    assert classify(view, limit) == verdict


# --------------------------------------------------------------- partition
def test_no_filter_puts_everything_in_matched(venues: list[VenueRow]):
    parts = partition(venues, [], 500)
    assert [v.venue_id for v in parts.matched] == ["10432", "11876", "10088"]
    assert parts.undocumented == []
    assert parts.not_available == 0


def test_unrecorded_is_grouped_not_removed(venues: list[VenueRow]):
    """AC1.2.3 — only a positively recorded absence leaves the lists."""
    parts = partition(venues, ["toilet", "change"], 500)
    assert [v.venue_id for v in parts.matched] == ["11876"]
    # Preston: change facility recorded at 1340 m — beyond the band, so open.
    assert [v.venue_id for v in parts.undocumented] == ["10432"]
    # Reservoir: toilet is not_available — removed, but counted.
    assert parts.not_available == 1


# ------------------------------------------------------------- parse_needs
def test_parse_needs_accepts_commas_repeats_and_aliases():
    assert parse_needs(["toilet,parking", "accessible_transport_stop", "Change"]) == [
        "toilet",
        "parking",
        "stop",
        "change",
    ]


def test_parse_needs_rejects_unknown_facility():
    with pytest.raises(ValueError, match="lift"):
        parse_needs(["toilet,lift"])
