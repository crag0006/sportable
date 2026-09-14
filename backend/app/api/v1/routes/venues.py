"""Search, the venue page, the corridor and the reserved directions endpoint."""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import Repo, SettingsDep
from app.api.params import (
    first_of,
    parse_band,
    parse_facilities,
    parse_from,
    parse_place,
    require_location,
)
from app.core.errors import ApiError
from app.domain.facilities import KEY_TO_KIND, FrontendKey, group
from app.domain.presenters import corridor_out, search_out, venue_card_out
from app.schemas.venues import CorridorOut, SearchOut, VenueCardOut

router = APIRouter()

# US2.2 names these three; change facilities are available on request.
DEFAULT_CORRIDOR_TYPES: tuple[FrontendKey, ...] = ("toilet", "parking", "stop")


@router.get("/venues/search", response_model=SearchOut, response_model_exclude_none=True)
def search(
    request: Request,
    repo: Repo,
    settings: SettingsDep,
    sport: Annotated[str, Query(description="A sport name from /sports.", examples=["Basketball"])],
    suburb: Annotated[
        str | None,
        Query(description='Suburb, with or without a postcode: "Preston 3072". Alias: place.'),
    ] = None,
    postcode: Annotated[
        str | None,
        Query(description="Four-digit postcode. Give suburb, postcode or near."),
    ] = None,
    near: Annotated[
        str | None,
        Query(description='"lat,lon" from browser geolocation. Give suburb, postcode or near.'),
    ] = None,
    facilities: Annotated[
        list[str] | None,
        Query(
            description="Access requirements: comma list of accessible_toilet, "
            "accessible_parking, accessible_transport_stop, accessible_change_facility. "
            "Aliases: needs, types, amenities, or flag style toilet=true."
        ),
    ] = None,
    distance_m: Annotated[
        int | None,
        Query(
            description="Facility distance limit in metres, one of the bands in /config. "
            "Aliases: limit, within.",
            examples=[500],
        ),
    ] = None,
) -> SearchOut:
    """Venues for a sport near a place, in three groups (contract v0.2 §4)."""
    q = request.query_params
    cfg = settings.search

    sport = (q.get("sport") or "").strip()
    if not sport:
        raise ApiError(422, "validation_error", "sport is required")

    keys = parse_facilities(request)
    kinds = [KEY_TO_KIND[key] for key in keys]
    limit_m = parse_band(first_of(request, "distance_m", "limit", "within"), cfg)

    near_raw = q.get("near")
    if near_raw and near_raw.strip():
        reference = parse_from(near_raw, repo)
        assert reference is not None
        place = "your location"
    else:
        suburb, postcode = parse_place(q.get("suburb") or q.get("place"), q.get("postcode"))
        if not suburb and not postcode:
            raise ApiError(422, "validation_error", "suburb, postcode or near is required")
        place = " ".join(p for p in (suburb, postcode) if p)
        reference = require_location(repo, suburb, postcode, place)

    venues = repo.search(sport, reference, cfg.search_radius_m)
    groups = group(venues, kinds, limit_m)
    latest = max((v.retrieved_at for v in venues if v.retrieved_at is not None), default=None)

    return search_out(
        sport=sport,
        reference=reference,
        limit_m=limit_m,
        radius_m=cfg.search_radius_m,
        kinds=kinds,
        total=len(venues),
        groups=groups,
        max_results=cfg.max_results,
        stale_default=cfg.default_stale_after_days,
        place=place,
        retrieved_at=latest,
    )


@router.get("/venues/{venue_id}", response_model=VenueCardOut, response_model_exclude_none=True)
def venue(
    venue_id: str,
    request: Request,
    repo: Repo,
    settings: SettingsDep,
    from_: Annotated[
        str | None,
        Query(
            alias="from",
            description='Optional starting point: "Preston 3072", "3072" or "lat,lon". '
            "Adds distance_m and reference_point to the page.",
        ),
    ] = None,
    distance_m: Annotated[
        int | None,
        Query(description="Evaluate the four tiles at this band. Default from /config."),
    ] = None,
) -> VenueCardOut:
    """The venue page (contract v0.2 §5)."""
    row = repo.get_venue(venue_id)
    if row is None:
        raise ApiError(404, "venue_not_found", f"No venue with id {venue_id!r}.")
    cfg = settings.search
    reference = parse_from(request.query_params.get("from"), repo)
    limit_m = parse_band(first_of(request, "distance_m", "limit"), cfg)
    return venue_card_out(row, reference, limit_m, cfg.default_stale_after_days)


@router.get(
    "/venues/{venue_id}/corridor",
    response_model=CorridorOut,
    response_model_exclude_none=True,
)
def corridor(
    venue_id: str,
    request: Request,
    repo: Repo,
    settings: SettingsDep,
    from_: Annotated[
        str,
        Query(
            alias="from",
            description='Starting point: "Preston 3072", "3072" or "lat,lon". '
            "Required, there is no default origin (AC2.2.1).",
        ),
    ],
    within: Annotated[
        int | None,
        Query(
            description="Corridor half-width in metres, one of the bands in /config. "
            "Default corridor_default_m."
        ),
    ] = None,
    types: Annotated[
        str | None,
        Query(
            description="Comma list of facility types. "
            "Default: accessible_toilet, accessible_parking, accessible_transport_stop."
        ),
    ] = None,
) -> CorridorOut:
    """US2.2 / US2.3 - the straight-line corridor (ADR-003). Not a route."""
    row = repo.get_venue(venue_id)
    if row is None:
        raise ApiError(404, "venue_not_found", f"No venue with id {venue_id!r}.")
    cfg = settings.search
    origin = parse_from(request.query_params.get("from"), repo)
    if origin is None:
        raise ApiError(
            422,
            "validation_error",
            "from is required: a suburb, postcode or latitude,longitude starting point",
        )
    within_m = parse_band(first_of(request, "within", "limit"), cfg, cfg.corridor_default_m)
    keys = parse_facilities(request) or list(DEFAULT_CORRIDOR_TYPES)
    result = repo.corridor(origin, row, within_m, [KEY_TO_KIND[key] for key in keys])
    return corridor_out(row, origin, within_m, keys, result, cfg.default_stale_after_days)


@router.get("/venues/{venue_id}/directions", include_in_schema=True)
def directions(venue_id: str, repo: Repo) -> None:
    """Reserved for the routed journey (contract v0.2 §6.2). 404 until Epic 4."""
    if repo.get_venue(venue_id) is None:
        raise ApiError(404, "venue_not_found", f"No venue with id {venue_id!r}.")
    raise ApiError(
        404,
        "not_implemented",
        "Routed directions are not available yet. Use /venues/{id}/corridor.",
    )
