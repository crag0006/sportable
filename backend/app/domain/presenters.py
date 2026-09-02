"""Build response models from repository rows."""

from datetime import date, datetime

from app.domain.facilities import (
    FRONTEND_KEYS,
    KEY_TO_KIND,
    KIND_TO_KEY,
    FrontendKey,
    rows_by_key,
    to_view,
    views_for,
)
from app.domain.geo import haversine_m
from app.repositories.protocols import (
    ChainRow,
    CorridorResult,
    FacilityRow,
    ReferencePoint,
    VenueRow,
)
from app.schemas.venues import (
    AmenityDetailOut,
    AmenityOut,
    CorridorFacilityOut,
    CorridorOut,
    CorridorPathOut,
    CorridorTypeOut,
    CorridorTypeStatus,
    CorridorVenueOut,
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


# ------------------------------------------------------------------ corridor
TYPE_LABELS: dict[str, str] = {
    "toilet": "Accessible toilets",
    "parking": "Accessible parking bays",
    "stop": "Accessible transport stops",
    "change": "Accessible change facilities",
}

STEP_FREE_NOT_CHECKED = (
    "Whether any path between these points is step-free - "
    "no dataset records kerb ramps, gradients or crossings."
)
OPENING_NOT_CHECKED = "Whether a facility is open or unlocked at the time you travel."


def _join_labels(labels: list[str]) -> str:
    lowered = [labels[0]] + [label.lower() for label in labels[1:]]
    if len(lowered) == 1:
        return lowered[0]
    return ", ".join(lowered[:-1]) + " and " + lowered[-1]


def corridor_out(
    venue: VenueRow,
    origin: ReferencePoint,
    within_m: int,
    keys: list[FrontendKey],
    result: CorridorResult,
) -> CorridorOut:
    """AC2.2 / AC2.3 - the straight-line corridor, honestly labelled (ADR-003)."""
    length_m = round(
        haversine_m(origin.latitude, origin.longitude, venue.latitude, venue.longitude)
    )
    counts: dict[str, int] = {key: 0 for key in keys}
    latest = venue.retrieved_at
    facilities: list[CorridorFacilityOut] = []
    for seq, row in enumerate(result.facilities, start=1):
        key = KIND_TO_KEY[row.kind]
        counts[key] = counts.get(key, 0) + 1
        if row.retrieved_at is not None and (latest is None or row.retrieved_at > latest):
            latest = row.retrieved_at
        source = None
        if row.source_name:
            source = SourceOut(
                name=row.source_name,
                published_at=_iso(row.source_updated),
                retrieved_at=_iso(row.retrieved_at),
            )
        facilities.append(
            CorridorFacilityOut(
                seq=seq,
                type=key,
                name=row.name,
                address=row.address,
                lat=row.lat,
                lon=row.lon,
                distance_from_path_m=round(row.distance_from_path_m),
                along_path_m=round(row.fraction * length_m),
                opening_hours=row.opening_hours,
                mlak=row.key_required,
                source=source,
            )
        )
    types: list[CorridorTypeOut] = []
    for key in keys:
        total = result.totals.get(KEY_TO_KIND[key], 0)
        count = counts.get(key, 0)
        status: CorridorTypeStatus = "found" if count else ("none_within" if total else "no_data")
        types.append(CorridorTypeOut(type=key, label=TYPE_LABELS[key], count=count, status=status))

    checked_labels = [t.label for t in types if t.status != "no_data"]
    checked = (
        [
            f"{_join_labels(checked_labels)} recorded in published datasets within "
            f"{within_m} m of a straight line from {origin.label} to {venue.name}."
        ]
        if checked_labels
        else []
    )
    not_checked = [STEP_FREE_NOT_CHECKED]
    not_checked.extend(
        f"{t.label} - no dataset for this facility type is loaded yet."
        for t in types
        if t.status == "no_data"
    )
    not_checked.append(OPENING_NOT_CHECKED)

    return CorridorOut(
        venue=CorridorVenueOut(
            id=venue.venue_id,
            name=venue.name,
            address=venue.address,
            lat=venue.latitude,
            lon=venue.longitude,
        ),
        origin=ReferencePointOut(
            label=origin.label, latitude=origin.latitude, longitude=origin.longitude
        ),
        path=CorridorPathOut(
            length_m=length_m,
            within_m=within_m,
            coordinates=[
                [origin.latitude, origin.longitude],
                [venue.latitude, venue.longitude],
            ],
        ),
        types=types,
        facilities=facilities,
        checked=checked,
        not_checked=not_checked,
        retrieved_at=_iso(latest),
    )
