"""Translate the database's facility vocabulary into what the interface renders.

THE ONE RULE — "unknown is never a no."

The database stores three publication states per venue and facility kind
(``confirmed`` / ``not_available`` / ``no_published_information``) plus the
straight-line distance to the nearest recorded amenity, which the status builder
keeps up to 5 km even when it marks anything beyond 1 km as unpublished.

The interface (Iteration 1 contract, ``frontend/src/data/Venues.js``) renders
four states per amenity:

    confirmed  the venue's own record says it is there — "At the venue"
    recorded   a source gives a distance in metres
    absent     a source positively records it is not there
    none       nobody has published anything

The two edge cases the Data team named map like this:

    confirmed + no distance            -> confirmed   ("at the venue")
    no_published_information + distance-> recorded    (the UI compares the
                                          distance with the selected band and
                                          says "beyond your limit")

A published-but-far amenity is therefore never rendered with the "no published
information" sentence, and a genuinely unpublished one never gets a distance.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.repositories.protocols import FacilityRow, VenueRow

FrontendKey = Literal["toilet", "parking", "stop", "change"]
FRONTEND_KEYS: tuple[FrontendKey, ...] = ("toilet", "parking", "stop", "change")

KIND_TO_KEY: dict[str, FrontendKey] = {
    "accessible_toilet": "toilet",
    "accessible_parking": "parking",
    "accessible_transport_stop": "stop",
    "accessible_change_facility": "change",
}

# Everything a client might reasonably send for a facility filter.
KEY_ALIASES: dict[str, FrontendKey] = {
    "toilet": "toilet",
    "toilets": "toilet",
    "accessible_toilet": "toilet",
    "parking": "parking",
    "accessible_parking": "parking",
    "stop": "stop",
    "stops": "stop",
    "transport": "stop",
    "accessible_transport_stop": "stop",
    "step_free_transport_stop": "stop",
    "change": "change",
    "changing": "change",
    "change_facility": "change",
    "accessible_change_facility": "change",
}

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
    return {KIND_TO_KEY[f.kind]: f for f in venue.facilities if f.kind in KIND_TO_KEY}


def views_for(venue: VenueRow) -> dict[FrontendKey, AmenityView]:
    """All four keys, always present, always in the same order."""
    rows = rows_by_key(venue)
    return {key: to_view(rows.get(key)) for key in FRONTEND_KEYS}


Verdict = Literal["pass", "open", "fail"]


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


def parse_needs(values: Iterable[str]) -> list[FrontendKey]:
    """Accept ``toilet,parking``, repeated params, or any of the known aliases.

    Raises ValueError naming the first token that is not a facility.
    """
    needs: list[FrontendKey] = []
    for raw in values:
        for token in raw.split(","):
            name = token.strip().lower()
            if not name:
                continue
            key = KEY_ALIASES.get(name)
            if key is None:
                raise ValueError(name)
            if key not in needs:
                needs.append(key)
    return needs
