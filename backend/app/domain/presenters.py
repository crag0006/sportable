"""Build response models from repository rows."""

from datetime import date, datetime

from app.domain.facilities import FRONTEND_KEYS, rows_by_key, to_view, views_for
from app.domain.geo import haversine_m
from app.repositories.protocols import ChainRow, FacilityRow, ReferencePoint, VenueRow
from app.schemas.venues import (
    AmenityDetailOut,
    AmenityOut,
    Location,
    ReferencePointOut,
    SourceOut,
    UnpublishedOut,
    VenueCardOut,
    VenueOut,
)

# AC2.1.5 — the two links no Australian dataset publishes at venue level.
UNPUBLISHED_LINKS: dict[str, tuple[str, str]] = {
    "enter": (
        "Step-free entry",
        "No Victorian dataset publishes step-free entry for sports venues. Check with the venue.",
    ),
    "play": (
        "Playing-surface access",
        "No dataset publishes court or playing-surface accessibility. Check with the venue.",
    ),
}


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _sports(venue: VenueRow) -> list[str]:
    seen: list[str] = []
    for entry in venue.sports:
        if entry.sport not in seen:
            seen.append(entry.sport)
    return seen


def _surface(venue: VenueRow) -> str | None:
    surfaces: list[str] = []
    for entry in venue.sports:
        if entry.surface_type and entry.surface_type not in surfaces:
            surfaces.append(entry.surface_type)
    return " / ".join(surfaces) if surfaces else None


def _distance_km(distance_m: float | None) -> float:
    return round((distance_m or 0.0) / 1000, 1)


def venue_out(venue: VenueRow) -> VenueOut:
    return VenueOut(
        id=venue.venue_id,
        name=venue.name,
        suburb=venue.suburb,
        postcode=venue.postcode,
        sports=_sports(venue),
        surface=_surface(venue),
        distance=_distance_km(venue.distance_m),
        amenities={
            key: AmenityOut(state=view.state, distance=view.distance)
            for key, view in views_for(venue).items()
        },
    )


def _location(row: FacilityRow) -> Location:
    """AC2.1.3 — inside the venue, a separate public facility nearby, or unrecorded."""
    if row.basis == "publisher_attribute" or row.is_inside_venue:
        return "at_venue"
    if row.amenity_name is not None or row.distance_m is not None:
        return "public_nearby"
    return "unrecorded"


def _source(row: FacilityRow) -> SourceOut | None:
    if not row.source_name:
        return None
    return SourceOut(
        name=row.source_name,
        published_at=_iso(row.source_updated),
        retrieved_at=_iso(row.retrieved_at),
    )


def _detail(row: FacilityRow | None) -> AmenityDetailOut:
    view = to_view(row)
    if row is None or view.state == "none":
        return AmenityDetailOut(state=view.state)
    if row.basis == "publisher_attribute":
        # Sourced to the venue's own dataset. Any amenity joined to this row is
        # a separate public facility nearby; its name and hours are not the
        # venue's and are not shown here.
        return AmenityDetailOut(state=view.state, location="at_venue", source=_source(row))
    return AmenityDetailOut(
        state=view.state,
        distance=view.distance,
        location=_location(row),
        name=row.amenity_name,
        lat=row.amenity_lat,
        lon=row.amenity_lon,
        opening_hours=row.opening_hours,
        mlak=row.key_required,
        source=_source(row),
    )


def _unpublished(chain: tuple[ChainRow, ...]) -> list[UnpublishedOut]:
    by_link = {c.link: c for c in chain}
    items: list[UnpublishedOut] = []
    for link, (label, default_reason) in UNPUBLISHED_LINKS.items():
        row = by_link.get(link)
        reason = row.detail if row is not None and row.detail else default_reason
        items.append(UnpublishedOut(key=link, label=label, reason=reason))
    return items


def venue_card_out(venue: VenueRow, reference: ReferencePoint | None = None) -> VenueCardOut:
    """The card. With a ``reference`` (``?from=``) it also says how far away it is."""
    rows = rows_by_key(venue)
    distance_km: float | None = None
    reference_out: ReferencePointOut | None = None
    if reference is not None:
        metres = haversine_m(
            reference.latitude, reference.longitude, venue.latitude, venue.longitude
        )
        distance_km = _distance_km(metres)
        reference_out = ReferencePointOut(
            label=reference.label, latitude=reference.latitude, longitude=reference.longitude
        )
    return VenueCardOut(
        distance=distance_km,
        reference_point=reference_out,
        id=venue.venue_id,
        name=venue.name,
        address=venue.address,
        suburb=venue.suburb,
        postcode=venue.postcode,
        lga=venue.lga,
        lat=venue.latitude,
        lon=venue.longitude,
        sports=_sports(venue),
        surface=_surface(venue),
        amenities={key: _detail(rows.get(key)) for key in FRONTEND_KEYS},
        unpublished=_unpublished(venue.chain),
        last_updated=_iso(venue.retrieved_at),
    )
