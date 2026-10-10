"""Translate a facility status row into what the interface renders.

THE ONE RULE: "unknown is never a no."

The database stores three publication states per venue and facility kind
(``confirmed`` / ``not_available`` / ``no_published_information``) plus the
straight-line distance to the nearest recorded amenity, which the status
builder keeps up to 5 km even when it marks anything beyond 1 km as
unpublished. ``status`` is that tri-state evaluated at the distance limit the
request asked for, ``display`` is which of six tile presentations to render
and ``message`` is the fixed sentence for it (API_CONTRACT_v0.2 §2.2). The
rules live here and nowhere else, so search, the venue page, events and the
assistant cannot drift apart.
"""

from dataclasses import dataclass

from app.domain.facilities.vocabulary import KIND_LABELS, KINDS, Display, Status
from app.repositories.protocols import FacilityRow, VenueRow

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
        if row.distance_m is None:
            # Confirmed by proximity but the builder kept no distance: there
            # is nothing to say "beyond" of, so it is unknown, not "0 m away".
            return "no_published_information"
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
    """A distance rounded to whole metres; 0 when unknown."""
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
    """Everything the interface needs to draw one tile at the requested band."""
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
    """The venue's facility rows keyed by database kind."""
    return {f.kind: f for f in venue.facilities if f.kind in KINDS}


def presentations_for(venue: VenueRow, limit_m: int) -> list[Presentation]:
    """All four kinds, always present, always in the contract's order."""
    rows = rows_by_kind(venue)
    return [present(rows.get(kind), kind, limit_m) for kind in KINDS]
