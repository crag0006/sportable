"""The v0.1 four-state vocabulary, kept for the fields the frontend still reads.

``amenities``, ``surface``, ``matched`` and ``undocumented`` are deprecated in
contract v0.2 (§11) and go away when the frontend finishes the switch. Nothing
new should import this module.

    confirmed  the venue's own record says it is there ("At the venue")
    recorded   a source gives a distance in metres
    absent     a source positively records it is not there
    none       nobody has published anything
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.domain.facilities.grouping import Verdict
from app.domain.facilities.vocabulary import FRONTEND_KEYS, KIND_TO_KEY, FrontendKey
from app.repositories.protocols import FacilityRow, VenueRow

State = Literal["confirmed", "recorded", "absent", "none"]


@dataclass(frozen=True)
class AmenityView:
    state: State
    distance: int | None = None


def to_view(row: FacilityRow | None) -> AmenityView:
    """Map one database status row to the interface's four-state vocabulary."""
    if row is None:
        return AmenityView("none")
    if row.status == "not_available":
        return AmenityView("absent")
    # The venue's own record says it is there. The status builder may still
    # store the nearest public amenity's distance alongside it — that distance
    # belongs to a different facility and must not demote "at the venue".
    if row.status == "confirmed" and (row.basis == "publisher_attribute" or row.distance_m is None):
        return AmenityView("confirmed")
    if row.distance_m is not None:
        return AmenityView("recorded", round(row.distance_m))
    return AmenityView("none")


def rows_by_key(venue: VenueRow) -> dict[FrontendKey, FacilityRow]:
    """The venue's facility rows keyed by frontend key."""
    return {KIND_TO_KEY[f.kind]: f for f in venue.facilities if f.kind in KIND_TO_KEY}


def views_for(venue: VenueRow) -> dict[FrontendKey, AmenityView]:
    """All four keys, always present, always in the same order."""
    rows = rows_by_key(venue)
    return {key: to_view(rows.get(key)) for key in FRONTEND_KEYS}


def classify(view: AmenityView, limit_m: int) -> Verdict:
    """Score one selected amenity against the chosen distance band.

    pass  — at the venue, or recorded within the band
    open  — nothing published, or recorded beyond the band ("beyond your limit")
    fail  — a source positively records it is not there
    """
    if view.state == "confirmed":
        return "pass"
    if view.state == "absent":
        return "fail"
    if view.state == "recorded" and view.distance is not None and view.distance <= limit_m:
        return "pass"
    return "open"


@dataclass(frozen=True)
class Partition:
    matched: list[VenueRow]
    undocumented: list[VenueRow]
    not_available: int


def partition(venues: Sequence[VenueRow], needs: Sequence[FrontendKey], limit_m: int) -> Partition:
    """Split sport matches into the two lists the interface shows.

    AC1.2.3: a venue with no published information for a filtered facility is
    grouped and counted, never silently removed. Only a positively recorded
    absence takes a venue out of both lists — and even that stays visible as a
    count.
    """
    if not needs:
        return Partition(list(venues), [], 0)

    matched: list[VenueRow] = []
    undocumented: list[VenueRow] = []
    not_available = 0
    for venue in venues:
        views = views_for(venue)
        verdicts = {classify(views[key], limit_m) for key in needs}
        if "fail" in verdicts:
            not_available += 1
        elif "open" in verdicts:
            undocumented.append(venue)
        else:
            matched.append(venue)
    return Partition(matched, undocumented, not_available)
