"""Build response models from repository rows.

Contract v0.2 shapes, each carrying the v0.1 fields alongside until the
Iteration 2 freeze (contract §11). The v0.1 translation (``to_view``,
``views_for``) is only used to fill those deprecated fields.
"""

from datetime import date, datetime

from app.domain.facilities import (
    FRONTEND_KEYS,
    KEY_TO_KIND,
    KIND_LABELS,
    FrontendKey,
    Groups,
    Presentation,
    presentations_for,
    rows_by_key,
    to_view,
    views_for,
)
from app.domain.geo import haversine_m
from app.domain.provenance import SourceRef, source_ref
from app.repositories.protocols import (
    ChainRow,
    CorridorResult,
    FacilityRow,
    ReferencePoint,
    SourceRow,
    VenueRow,
)
from app.schemas.common import (
    AlternativeOut,
    DetailSourceOut,
    FacilityDetailOut,
    FacilityOut,
    ReferencePointOut,
    SourceRefOut,
)
from app.schemas.sources import SourceOut as RegisterSourceOut
from app.schemas.sources import SourceStatus
from app.schemas.venues import (
    AccessLinkOut,
    AmenityDetailOut,
    AmenityOut,
    CorridorFacilityOut,
    CorridorOut,
    CorridorPathOut,
    CorridorTypeOut,
    CorridorTypeStatus,
    CorridorVenueOut,
    CountsOut,
    GroupOut,
    LimitItemOut,
    LimitsOut,
    Location,
    SearchOut,
    SearchVenueOut,
    SourceOut,
    UnpublishedOut,
    UpcomingEventsOut,
    VenueCardOut,
)

# AC2.1.5 - the two links no Australian dataset publishes at venue level.
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

# The six links of venue_access_chain, in journey order (data/sql/004).
CHAIN_LINKS: tuple[tuple[str, str, str | None], ...] = (
    ("arrive_parking", "Arrive by car", "accessible_parking"),
    ("arrive_transport", "Arrive by transport", "accessible_transport_stop"),
    ("enter", "Enter the building", None),
    ("toilet", "Use a toilet", "accessible_toilet"),
    ("change", "Change", "accessible_change_facility"),
    ("play", "Reach the playing surface", None),
)

LIMITS_HEADING = "What this page cannot tell you"
LIMIT_ITEMS: tuple[tuple[str, str], ...] = (
    ("Step-free entry to the building", "No available dataset records it."),
    ("Access to the playing surface", "No available dataset records it."),
    ("Whether a recorded distance is walkable", "Distances are straight-line, not a checked path."),
    (
        "Whether a facility is open or unlocked when you visit",
        "Opening hours are as published; nothing here is checked live.",
    ),
)

CORRIDOR_DISCLAIMER = (
    "This is a straight-line corridor, not a route. "
    "Nothing here confirms that any path is step-free."
)


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _href(venue_id: str) -> str:
    return f"/venues/{venue_id}"


def _sports(venue: VenueRow) -> list[str]:
    seen: list[str] = []
    for entry in venue.sports:
        if entry.sport not in seen:
            seen.append(entry.sport)
    return seen


def _surface_types(venue: VenueRow) -> list[str]:
    if venue.surface_types:
        return list(venue.surface_types)
    surfaces: list[str] = []
    for entry in venue.sports:
        if entry.surface_type and entry.surface_type not in surfaces:
            surfaces.append(entry.surface_type)
    return surfaces


def _surface(venue: VenueRow) -> str | None:
    surfaces = _surface_types(venue)
    return " / ".join(surfaces) if surfaces else None


def _distance_km(distance_m: float | None) -> float:
    return round((distance_m or 0.0) / 1000, 1)


def _metres(distance_m: float | None) -> int:
    return round(distance_m or 0.0)


def reference_out(reference: ReferencePoint) -> ReferencePointOut:
    kind = reference.kind if reference.kind in ("suburb", "postcode", "point") else "suburb"
    return ReferencePointOut(
        label=reference.label,
        kind=kind,
        code=reference.code,
        latitude=reference.latitude,
        longitude=reference.longitude,
    )


# ------------------------------------------------------------- provenance
def _ref_out(ref: SourceRef | None) -> SourceRefOut | None:
    if ref is None:
        return None
    return SourceRefOut(
        id=ref.id,
        name=ref.name,
        publisher_last_updated=_iso(ref.publisher_last_updated),
        retrieved_at=_iso(ref.retrieved_at),
        possibly_out_of_date=ref.possibly_out_of_date,
        stale_after_days=ref.stale_after_days,
    )


def _status_source(row: FacilityRow, stale_default: int) -> SourceRef | None:
    return source_ref(
        row.source_name,
        source_id=row.source_id,
        publisher_last_updated=row.source_updated,
        retrieved_at=row.retrieved_at,
        stale_after_days=row.stale_after_days,
        default_stale_after_days=stale_default,
    )


# ------------------------------------------------------------- v0.2 tiles
def _location_sentence(row: FacilityRow) -> str:
    if row.location_relative_to_venue:
        return row.location_relative_to_venue
    if row.basis == "publisher_attribute" or row.is_inside_venue:
        return "at the venue"
    if row.amenity_name is not None or row.distance_m is not None:
        return "a separate public facility nearby"
    return "no source records whether this is inside the venue or nearby"


def _detail_out(p: Presentation, stale_default: int) -> FacilityDetailOut | None:
    """Present whenever a recorded amenity describes the tile (contract §5)."""
    row = p.row
    if row is None or p.display not in ("at_venue", "nearby", "beyond_limit"):
        return None
    from_publisher = row.basis == "publisher_attribute"
    detail_source: DetailSourceOut | None = None
    if row.detail_amenity_id:
        ref = source_ref(
            row.detail_source_name,
            source_id=row.detail_source_id,
            publisher_last_updated=row.detail_source_updated,
            retrieved_at=row.retrieved_at,
            default_stale_after_days=stale_default,
        )
        if ref is not None:
            detail_source = DetailSourceOut(
                **_ref_out(ref).model_dump(),  # type: ignore[union-attr]
                distance_m=_metres(row.detail_distance_m) if row.detail_distance_m else None,
            )
    described = (not from_publisher) or bool(row.detail_amenity_id)
    return FacilityDetailOut(
        location_relative_to_venue=_location_sentence(row),
        # The nearest amenity's identity and position belong to the tile only
        # when that amenity is the answer. On a publisher-confirmed row it may
        # be an unrelated facility down the road.
        name=row.amenity_name if not from_publisher else None,
        address=row.amenity_address if not from_publisher else None,
        latitude=row.amenity_lat if not from_publisher else None,
        longitude=row.amenity_lon if not from_publisher else None,
        opening_hours=row.opening_hours if described else None,
        opening_hours_unrecorded=bool(row.opening_hours_unrecorded)
        if row.opening_hours_unrecorded is not None
        else (row.opening_hours is None),
        key_required=row.key_required if described else None,
        key_requirement_unrecorded=bool(row.key_requirement_unrecorded)
        if row.key_requirement_unrecorded is not None
        else (row.key_required is None),
        mlak_24h=row.mlak_24h if described else None,
        payment_required=row.payment_required if described else None,
        left_hand_transfer=row.left_hand_transfer if described else None,
        right_hand_transfer=row.right_hand_transfer if described else None,
        ambulant=row.ambulant if described else None,
        changing_places=row.changing_places if described else None,
        has_shower=row.has_shower if described else None,
        access_note=row.access_note if described else None,
        transport_mode=row.transport_mode,
        detail_source=detail_source,
    )


def _alternative_out(p: Presentation, stale_default: int) -> AlternativeOut | None:
    row = p.row
    if row is None or p.display != "not_available_alternative":
        return None
    ref = source_ref(
        row.alternative_source_name,
        source_id=row.alternative_source_id,
        publisher_last_updated=row.alternative_source_updated,
        retrieved_at=row.retrieved_at,
        default_stale_after_days=stale_default,
    )
    return AlternativeOut(
        name=row.alternative_name,
        distance_m=_metres(row.alternative_distance_m),
        opening_hours=row.alternative_opening_hours,
        key_required=row.alternative_key_required,
        latitude=row.alternative_lat,
        longitude=row.alternative_lon,
        source=_ref_out(ref),
    )


def facility_out(p: Presentation, stale_default: int, with_detail: bool = False) -> FacilityOut:
    """§2.2 - the one tile object every page shares."""
    source = _status_source(p.row, stale_default) if p.row is not None else None
    if p.display == "no_published_information":
        source = None
    return FacilityOut(
        type=p.kind,
        label=p.label,
        status=p.status,
        basis=p.basis,
        display=p.display,
        distance_m=p.distance_m,
        distance_limit_m=p.distance_limit_m,
        message=p.message,
        source=_ref_out(source),
        alternative=_alternative_out(p, stale_default),
        detail=_detail_out(p, stale_default) if with_detail else None,
    )


def facilities_out(
    venue: VenueRow, limit_m: int, stale_default: int, with_detail: bool = False
) -> list[FacilityOut]:
    return [facility_out(p, stale_default, with_detail) for p in presentations_for(venue, limit_m)]


# ------------------------------------------------------------- v0.1 tiles
def _amenities_compat(venue: VenueRow) -> dict[str, AmenityOut]:
    return {
        key: AmenityOut(state=view.state, distance=view.distance)
        for key, view in views_for(venue).items()
    }


def _location_compat(row: FacilityRow) -> Location:
    if row.basis == "publisher_attribute" or row.is_inside_venue:
        return "at_venue"
    if row.amenity_name is not None or row.distance_m is not None:
        return "public_nearby"
    return "unrecorded"


def _source_compat(row: FacilityRow) -> SourceOut | None:
    if not row.source_name:
        return None
    return SourceOut(
        name=row.source_name,
        published_at=_iso(row.source_updated),
        retrieved_at=_iso(row.retrieved_at),
    )


def _detail_compat(row: FacilityRow | None) -> AmenityDetailOut:
    view = to_view(row)
    if row is None or view.state == "none":
        return AmenityDetailOut(state=view.state)
    if row.basis == "publisher_attribute":
        return AmenityDetailOut(state=view.state, location="at_venue", source=_source_compat(row))
    return AmenityDetailOut(
        state=view.state,
        distance=view.distance,
        location=_location_compat(row),
        name=row.amenity_name,
        lat=row.amenity_lat,
        lon=row.amenity_lon,
        opening_hours=row.opening_hours,
        mlak=row.key_required,
        source=_source_compat(row),
    )


def _unpublished_compat(chain: tuple[ChainRow, ...]) -> list[UnpublishedOut]:
    by_link = {c.link: c for c in chain}
    items: list[UnpublishedOut] = []
    for link, (label, default_reason) in UNPUBLISHED_LINKS.items():
        row = by_link.get(link)
        reason = row.detail if row is not None and row.detail else default_reason
        items.append(UnpublishedOut(key=link, label=label, reason=reason))
    return items


# ------------------------------------------------------------------ search
def search_venue_out(venue: VenueRow, limit_m: int, stale_default: int) -> SearchVenueOut:
    return SearchVenueOut(
        id=venue.venue_id,
        name=venue.name,
        address=venue.address,
        suburb=venue.suburb,
        postcode=venue.postcode,
        lga=venue.lga,
        latitude=venue.latitude,
        longitude=venue.longitude,
        sports=_sports(venue),
        surface_types=_surface_types(venue),
        href=_href(venue.venue_id),
        distance_m=_metres(venue.distance_m),
        facilities=facilities_out(venue, limit_m, stale_default),
        distance=_distance_km(venue.distance_m),
        surface=_surface(venue),
        amenities=_amenities_compat(venue),
    )


def venue_out(venue: VenueRow, limit_m: int = 500, stale_default: int = 365) -> SearchVenueOut:
    """Alias kept for the v0.1 call sites."""
    return search_venue_out(venue, limit_m, stale_default)


def _join(labels: list[str], word: str) -> str:
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f" {word} " + labels[-1]


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def search_out(
    *,
    sport: str,
    reference: ReferencePoint,
    limit_m: int,
    radius_m: int,
    kinds: list[str],
    total: int,
    groups: Groups,
    max_results: int,
    stale_default: int,
    place: str,
    retrieved_at: datetime | None,
) -> SearchOut:
    """§4 - three groups. A venue is never dropped, only grouped and counted."""
    labels = [KIND_LABELS[k].lower() for k in kinds]
    results = [search_venue_out(v, limit_m, stale_default) for v in groups.matched[:max_results]]
    undocumented = [
        search_venue_out(v, limit_m, stale_default) for v in groups.undocumented[:max_results]
    ]
    not_available = [
        search_venue_out(v, limit_m, stale_default) for v in groups.not_available[:max_results]
    ]
    n_undoc, n_na = len(groups.undocumented), len(groups.not_available)
    undocumented_label = (
        f"{_plural(n_undoc, 'more venue')} have no published information about "
        f"{_join(labels, 'or')}"
        if kinds
        else "No facility filter applied"
    )
    not_available_label = (
        f"{_plural(n_na, 'venue')} record that they do not have {_join(labels, 'or')}"
        if kinds
        else "No facility filter applied"
    )
    return SearchOut(
        sport=sport,
        reference_point=reference_out(reference),
        distance_limit_m=limit_m,
        search_radius_m=radius_m,
        facilities_requested=list(kinds),
        counts=CountsOut(
            total_for_sport=total,
            matched=len(groups.matched),
            undocumented=n_undoc,
            not_available=n_na,
        ),
        results=results,
        undocumented_group=GroupOut(label=undocumented_label, count=n_undoc, results=undocumented),
        not_available_group=GroupOut(label=not_available_label, count=n_na, results=not_available),
        retrieved_at=_iso(retrieved_at),
        place=place,
        total=total,
        matched=results,
        undocumented=undocumented,
        not_available=n_na,
    )


# -------------------------------------------------------------- venue page
def _access_chain(venue: VenueRow, tiles: dict[str, FacilityOut]) -> list[AccessLinkOut]:
    by_link = {c.link: c for c in venue.chain}
    out: list[AccessLinkOut] = []
    for link, label, kind in CHAIN_LINKS:
        row = by_link.get(link)
        if kind is not None and kind in tiles:
            tile = tiles[kind]
            out.append(
                AccessLinkOut(
                    link=link,
                    label=label,
                    facility_type=kind,
                    status=tile.status,
                    summary=tile.message,
                )
            )
            continue
        default_label, default_reason = UNPUBLISHED_LINKS.get(link, (label, ""))
        summary = row.detail if row is not None and row.detail else default_reason
        out.append(
            AccessLinkOut(
                link=link,
                label=label,
                facility_type=None,
                status=row.status if row is not None else "no_published_information",
                summary=summary or default_label,
            )
        )
    return out


def _limits() -> LimitsOut:
    return LimitsOut(
        heading=LIMITS_HEADING,
        items=[LimitItemOut(topic=t, reason=r) for t, r in LIMIT_ITEMS],
    )


def _sources_used(tiles: list[FacilityOut]) -> list[SourceRefOut]:
    seen: dict[str, SourceRefOut] = {}
    for tile in tiles:
        for ref in (
            tile.source,
            tile.alternative.source if tile.alternative else None,
            tile.detail.detail_source if tile.detail else None,
        ):
            if ref is not None and ref.name not in seen:
                seen[ref.name] = SourceRefOut(**ref.model_dump(exclude={"distance_m"}))
    return list(seen.values())


def venue_card_out(
    venue: VenueRow,
    reference: ReferencePoint | None = None,
    limit_m: int = 500,
    stale_default: int = 365,
    upcoming: UpcomingEventsOut | None = None,
) -> VenueCardOut:
    """The venue page (§5). With ``reference`` (``?from=``) it also says how far."""
    rows = rows_by_key(venue)
    distance_m: int | None = None
    distance_km: float | None = None
    reference_point: ReferencePointOut | None = None
    if reference is not None:
        metres = haversine_m(
            reference.latitude, reference.longitude, venue.latitude, venue.longitude
        )
        distance_m = round(metres)
        distance_km = _distance_km(metres)
        reference_point = reference_out(reference)
    tiles = facilities_out(venue, limit_m, stale_default, with_detail=True)
    by_kind: dict[str, FacilityOut] = {t.type: t for t in tiles}
    return VenueCardOut(
        id=venue.venue_id,
        name=venue.name,
        address=venue.address,
        suburb=venue.suburb,
        postcode=venue.postcode,
        lga=venue.lga,
        latitude=venue.latitude,
        longitude=venue.longitude,
        sports=_sports(venue),
        surface_types=_surface_types(venue),
        href=_href(venue.venue_id),
        ownership=venue.ownership,
        purpose=venue.purpose,
        changeroom_description=venue.changeroom_description,
        facilities=tiles,
        access_chain=_access_chain(venue, by_kind),
        limits=_limits(),
        sources=_sources_used(tiles),
        upcoming_events=upcoming or UpcomingEventsOut(count=0),
        last_updated=_iso(venue.retrieved_at),
        distance_m=distance_m,
        reference_point=reference_point,
        lat=venue.latitude,
        lon=venue.longitude,
        surface=_surface(venue),
        amenities={key: _detail_compat(rows.get(key)) for key in FRONTEND_KEYS},
        unpublished=_unpublished_compat(venue.chain),
        distance=distance_km,
    )


# ----------------------------------------------------------------- sources
SOURCE_FEEDS: dict[str, list[str]] = {
    "DS-01": ["venues", "accessible_toilet", "accessible_parking"],
    "DS-02": ["accessible_toilet", "accessible_change_facility"],
    "DS-03": ["accessible_transport_stop"],
    "DS-04": ["accessible_parking"],
    "DS-05": ["directions"],
    "DS-06": ["coverage"],
    "DS-07": ["locations"],
    "DS-08": ["locations"],
    "DS-09": ["events"],
}
SOURCE_TIERS: dict[str, str] = {"DS-05": "live", "DS-09": "scheduled"}
SOURCE_NOTES: dict[str, str] = {
    "DS-05": (
        "Nothing it returns is stored. Credited because routing computes over OpenStreetMap."
    ),
}


def register_source_out(row: SourceRow, stale_default: int) -> RegisterSourceOut:
    ref = source_ref(
        row.name,
        source_id=row.source_id,
        publisher_last_updated=row.publisher_last_updated,
        retrieved_at=row.retrieved_at,
        stale_after_days=row.stale_after_days,
        default_stale_after_days=stale_default,
    )
    assert ref is not None  # name is NOT NULL in the register
    status: SourceStatus
    if row.source_id in SOURCE_TIERS and SOURCE_TIERS[row.source_id] == "live":
        status = "not_used"
    elif row.rows_loaded:
        status = "loaded"
    elif row.outcome and row.outcome not in ("landed", "ok", "success"):
        status = "failed_using_last_good"
    else:
        status = "empty"
    return RegisterSourceOut(
        id=row.source_id,
        name=row.name,
        publisher=row.publisher,
        licence=row.licence_name,
        licence_url=row.licence_url,
        attribution=row.attribution_text,
        url=row.landing_page or row.licence_url,
        tier=SOURCE_TIERS.get(row.source_id, "static"),
        publisher_scope=row.publisher_scope,
        publisher_last_updated=_iso(row.publisher_last_updated),
        retrieved_at=_iso(row.retrieved_at),
        stale_after_days=ref.stale_after_days,
        possibly_out_of_date=ref.possibly_out_of_date,
        feeds=SOURCE_FEEDS.get(row.source_id, []),
        status=status,
        row_count=row.rows_loaded,
        mode="sample" if row.source_id == "DS-09" and not row.rows_loaded else None,
        note=SOURCE_NOTES.get(row.source_id),
    )


# ---------------------------------------------------------------- corridor
CORRIDOR_LABELS: dict[str, str] = {
    "accessible_toilet": "Accessible toilets",
    "accessible_parking": "Accessible parking bays",
    "accessible_transport_stop": "Step-free railway stations",
    "accessible_change_facility": "Accessible change facilities",
}

STEP_FREE_NOT_CHECKED = (
    "Whether any path between these points is step-free. "
    "No dataset records kerb ramps, gradients or crossings."
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
    stale_default: int = 365,
) -> CorridorOut:
    """AC2.2 / AC2.3 - the straight-line corridor, honestly labelled (ADR-003)."""
    kinds = [KEY_TO_KIND[key] for key in keys]
    length_m = round(
        haversine_m(origin.latitude, origin.longitude, venue.latitude, venue.longitude)
    )
    counts: dict[str, int] = dict.fromkeys(kinds, 0)
    latest = venue.retrieved_at
    facilities: list[CorridorFacilityOut] = []
    for seq, row in enumerate(result.facilities, start=1):
        counts[row.kind] = counts.get(row.kind, 0) + 1
        if row.retrieved_at is not None and (latest is None or row.retrieved_at > latest):
            latest = row.retrieved_at
        ref = source_ref(
            row.source_name,
            publisher_last_updated=row.source_updated,
            retrieved_at=row.retrieved_at,
            default_stale_after_days=stale_default,
        )
        facilities.append(
            CorridorFacilityOut(
                seq=seq,
                type=row.kind,
                name=row.name,
                address=row.address,
                latitude=row.lat,
                longitude=row.lon,
                distance_from_path_m=round(row.distance_from_path_m),
                along_path_m=round(row.fraction * length_m),
                opening_hours=row.opening_hours,
                opening_hours_unrecorded=row.opening_hours is None,
                key_required=row.key_required,
                key_requirement_unrecorded=row.key_required is None,
                source=_ref_out(ref),
                lat=row.lat,
                lon=row.lon,
                mlak=row.key_required,
            )
        )
    types: list[CorridorTypeOut] = []
    for kind in kinds:
        total = result.totals.get(kind, 0)
        count = counts.get(kind, 0)
        status: CorridorTypeStatus = "found" if count else ("none_within" if total else "no_data")
        label = CORRIDOR_LABELS[kind]
        message: str | None = None
        if status == "none_within":
            message = f"No {label.lower()} recorded within {within_m} m of this line."
        elif status == "no_data":
            message = f"No published information loaded for {label.lower()}."
        types.append(
            CorridorTypeOut(type=kind, label=label, count=count, status=status, message=message)
        )

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
            latitude=venue.latitude,
            longitude=venue.longitude,
            href=_href(venue.venue_id),
            lat=venue.latitude,
            lon=venue.longitude,
        ),
        origin=reference_out(origin),
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
        disclaimer=CORRIDOR_DISCLAIMER,
        retrieved_at=_iso(latest),
    )
