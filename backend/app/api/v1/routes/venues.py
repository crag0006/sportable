"""Search, the venue page, the corridor and the reserved directions endpoint."""

from fastapi import APIRouter, Request

from app.api.deps import NowDep, SettingsDep, Venues
from app.api.params import first_of, parse_band, parse_facilities, parse_origin, place_input
from app.api.queries import (
    DistanceQ,
    FacilitiesQ,
    FromQ,
    NearQ,
    OriginQ,
    PostcodeQ,
    SportQ,
    SuburbQ,
    TypesQ,
    WithinQ,
)
from app.core.config import Settings
from app.core.errors import ApiError
from app.domain.facilities import KEY_TO_KIND
from app.schemas.venues import CorridorOut, SearchOut, VenueCardOut
from app.services.inputs import CorridorQuery, SearchQuery, VenuePageQuery

router = APIRouter()


def _search_query(request: Request, settings: Settings) -> SearchQuery:
    """Parse ``/venues/search``; sport and a place are required."""
    q = request.query_params
    sport = (q.get("sport") or "").strip()
    if not sport:
        raise ApiError(422, "validation_error", "sport is required")
    place = place_input(q.get("suburb") or q.get("place"), q.get("postcode"), q.get("near"))
    if place is None:
        raise ApiError(422, "validation_error", "suburb, postcode or near is required")
    keys = parse_facilities(request)
    return SearchQuery(
        sport=sport,
        place=place,
        kinds=[KEY_TO_KIND[key] for key in keys],
        limit_m=parse_band(first_of(request, "distance_m", "limit", "within"), settings.search),
    )


def corridor_query(request: Request, settings: Settings) -> CorridorQuery:
    """Parse a corridor request: origin, half-width band and facility types."""
    cfg = settings.search
    return CorridorQuery(
        origin=parse_origin(request.query_params.get("from")),
        within_m=parse_band(first_of(request, "within", "limit"), cfg, cfg.corridor_default_m),
        keys=parse_facilities(request),
    )


@router.get("/venues/search", response_model=SearchOut, response_model_exclude_none=True)
def search(
    request: Request,
    venues: Venues,
    settings: SettingsDep,
    sport: SportQ,
    suburb: SuburbQ = None,
    postcode: PostcodeQ = None,
    near: NearQ = None,
    facilities: FacilitiesQ = None,
    distance_m: DistanceQ = None,
) -> SearchOut:
    """Venues for a sport near a place, in three groups (contract v0.2 §4)."""
    return venues.search(_search_query(request, settings))


@router.get("/venues/{venue_id}", response_model=VenueCardOut, response_model_exclude_none=True)
def venue(
    venue_id: str,
    request: Request,
    venues: Venues,
    settings: SettingsDep,
    now: NowDep,
    from_: FromQ = None,
    distance_m: DistanceQ = None,
) -> VenueCardOut:
    """The venue page (contract v0.2 §5)."""
    query = VenuePageQuery(
        venue_id=venue_id,
        origin=parse_origin(request.query_params.get("from")),
        limit_m=parse_band(first_of(request, "distance_m", "limit"), settings.search),
    )
    return venues.page(query, now)


@router.get(
    "/venues/{venue_id}/corridor",
    response_model=CorridorOut,
    response_model_exclude_none=True,
)
def corridor(
    venue_id: str,
    request: Request,
    venues: Venues,
    settings: SettingsDep,
    from_: OriginQ,
    within: WithinQ = None,
    types: TypesQ = None,
) -> CorridorOut:
    """US2.2 / US2.3 - the straight-line corridor (ADR-003). Not a route."""
    return venues.corridor(venue_id, corridor_query(request, settings))


@router.get("/venues/{venue_id}/directions", include_in_schema=True)
def directions(venue_id: str, venues: Venues) -> None:
    """Reserved for the routed journey (contract v0.2 §6.2). 404 until Epic 4."""
    venues.load(venue_id)
    raise ApiError(
        404,
        "not_implemented",
        "Routed directions are not available yet. Use /venues/{id}/corridor.",
    )
