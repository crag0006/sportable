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

KEY_TO_KIND: dict[FrontendKey, str] = {key: kind for kind, key in KIND_TO_KEY.items()}

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


# =========================================================================
# v0.2 - one vocabulary end to end (API_CONTRACT_v0.2 §2.2)
#
# ``status`` is the database tri-state evaluated at the distance limit the
# request asked for, ``display`` is which of six tile presentations to render
# and ``message`` is the fixed sentence for it. The rules live here and
# nowhere else, so search, the venue page, events and the assistant cannot
# drift apart.
# =========================================================================

Kind = Literal[
    "accessible_toilet",
    "accessible_parking",
    "accessible_transport_stop",
    "accessible_change_facility",
]
KINDS: tuple[Kind, ...] = (
    "accessible_toilet",
    "accessible_parking",
    "accessible_transport_stop",
    "accessible_change_facility",
)

# Transport is labelled as what the data actually confirms: only railway
# stations publish wheelchair_boarding (Data Layer guide §2.3).
KIND_LABELS: dict[str, str] = {
    "accessible_toilet": "Accessible toilet",
    "accessible_parking": "Accessible parking",
    "accessible_transport_stop": "Step-free railway station",
    "accessible_change_facility": "Accessible change facility",
}

Status = Literal["confirmed", "not_available", "no_published_information"]
Display = Literal[
    "at_venue",
    "nearby",
    "beyond_limit",
    "not_available",
    "not_available_alternative",
    "no_published_information",
]

NO_INFORMATION = "No published information - check with the venue."


def within_limit(row: FacilityRow, limit_m: int) -> bool:
    """Is the nearest recorded facility inside the requested band?

    The precomputed band flags describe the nearest amenity, not the status
    (Data Layer guide §4.1). They are preferred when present because they were
    computed by the same builder that wrote ``distance_m``; the arithmetic is
    the fallback for rows that did not come from ``venue_facility_detail``.
    """
    flags = {250: row.within_250m, 500: row.within_500m, 1000: row.within_1000m}
    flag = flags.get(limit_m)
    if flag is not None:
        return flag
    return row.distance_m is not None and row.distance_m <= limit_m


def display(row: FacilityRow | None, limit_m: int) -> Display:
    """Which of the six presentations a tile gets. Normative table in §2.2."""
    if row is None:
        return "no_published_information"
    if row.status == "not_available":
        if row.alternative_distance_m is not None:
            return "not_available_alternative"
        return "not_available"
    if row.status == "confirmed":
        # A published attribute outranks proximity in both directions. The
        # distance the builder kept on a publisher-confirmed row belongs to a
        # different facility and never demotes "at the venue".
        if row.basis == "publisher_attribute" or row.is_inside_venue:
            return "at_venue"
        if within_limit(row, limit_m):
            return "nearby"
        return "beyond_limit"
    # no_published_information. The builder keeps the nearest amenity up to
    # 5 km; a recorded distance is shown, never the no-information sentence.
    if row.distance_m is not None:
        return "beyond_limit"
    return "no_published_information"


def effective_status(row: FacilityRow | None, limit_m: int) -> Status:
    """The tri-state at the requested band, derived from ``display``."""
    shown = display(row, limit_m)
    if shown in ("at_venue", "nearby"):
        return "confirmed"
    if shown in ("not_available", "not_available_alternative"):
        return "not_available"
    return "no_published_information"


def _metres(value: float | None) -> int:
    return round(value or 0.0)


def message(row: FacilityRow | None, kind: str, limit_m: int) -> str:
    """The display-ready sentence for the tile. Wording is fixed here."""
    label = KIND_LABELS.get(kind, kind).lower()
    shown = display(row, limit_m)
    if row is None or shown == "no_published_information":
        return NO_INFORMATION
    source = row.source_name
    if shown == "at_venue":
        return f"At the venue, per {source}." if source else "At the venue."
    if shown == "nearby":
        return f"Public {label} {_metres(row.distance_m)} m away (straight line)."
    if shown == "beyond_limit":
        return (
            f"Nearest recorded {label} is {_metres(row.distance_m)} m away, "
            f"beyond your {limit_m} m limit."
        )
    if shown == "not_available_alternative":
        return (
            f"Not at this venue. Nearest public {label} "
            f"{_metres(row.alternative_distance_m)} m away."
        )
    return f"Not available, per {source}." if source else "Not available."


@dataclass(frozen=True)
class Presentation:
    """Everything the interface needs to draw one tile, in one place."""

    kind: str
    label: str
    status: Status
    basis: str
    display: Display
    distance_m: int | None
    distance_limit_m: int
    message: str
    row: FacilityRow | None


def present(row: FacilityRow | None, kind: str, limit_m: int) -> Presentation:
    shown = display(row, limit_m)
    distance: int | None = None
    if row is not None and shown in ("nearby", "beyond_limit") and row.distance_m is not None:
        distance = _metres(row.distance_m)
    return Presentation(
        kind=kind,
        label=KIND_LABELS.get(kind, kind),
        status=effective_status(row, limit_m),
        basis=row.basis if row is not None else "not_published",
        display=shown,
        distance_m=distance,
        distance_limit_m=limit_m,
        message=message(row, kind, limit_m),
        row=row,
    )


def rows_by_kind(venue: VenueRow) -> dict[str, FacilityRow]:
    return {f.kind: f for f in venue.facilities if f.kind in KINDS}


def presentations_for(venue: VenueRow, limit_m: int) -> list[Presentation]:
    """All four kinds, always present, always in the contract's order."""
    rows = rows_by_kind(venue)
    return [present(rows.get(kind), kind, limit_m) for kind in KINDS]


def verdict(presentation: Presentation) -> Verdict:
    """pass = confirmed at the band, fail = a recorded absence, open = the rest."""
    if presentation.status == "confirmed":
        return "pass"
    if presentation.status == "not_available":
        return "fail"
    return "open"


@dataclass(frozen=True)
class Groups:
    """The three lists of §4. A venue is never dropped, only grouped."""

    matched: list[VenueRow]
    undocumented: list[VenueRow]
    not_available: list[VenueRow]


def group(venues: Sequence[VenueRow], kinds: Sequence[str], limit_m: int) -> Groups:
    """Partition by the requested kinds at the requested band (v0.2 §4).

    Unlike v0.1 ``partition``, venues with a recorded absence are listed as
    well as counted: a person who can use the nearby alternative still needs
    to find the venue.
    """
    if not kinds:
        return Groups(list(venues), [], [])
    matched: list[VenueRow] = []
    undocumented: list[VenueRow] = []
    not_available: list[VenueRow] = []
    for venue in venues:
        by_kind = {p.kind: p for p in presentations_for(venue, limit_m)}
        verdicts = {verdict(by_kind[kind]) for kind in kinds if kind in by_kind}
        if "fail" in verdicts:
            not_available.append(venue)
        elif "open" in verdicts:
            undocumented.append(venue)
        else:
            matched.append(venue)
    return Groups(matched, undocumented, not_available)


def parse_kinds(values: Iterable[str]) -> list[str]:
    """Like ``parse_needs`` but returns database kinds, in request order."""
    return [KEY_TO_KIND[key] for key in parse_needs(values)]
