"""The /api/v1 routes.

Paths are served under both the names the stub used (``/venues/search``,
``/sports``) and the names in the v0.1 contract draft (``/search``,
``/meta/sports``), so whichever the frontend wired up works.

Search parameters are parsed leniently on purpose — the frontend's request
shape was still moving when this shipped:

    sport=Basketball                       required
    suburb=Preston 3072 | suburb=Preston&postcode=3072 | postcode=3072
    needs=toilet,stop | amenities=toilet&amenities=stop | toilet=true&stop=true
    limit=500 | within=500 | distance_m=500   (one of config.distance_bands_m)

The venue card takes an optional starting point in the same spirit:

    /venues/{id}?from=Preston 3072 | from=3072 | from=-37.74,145.01
"""

import re
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import Repo, SettingsDep
from app.core.config import SearchConfig
from app.core.errors import ApiError
from app.domain.facilities import (
    FRONTEND_KEYS,
    KEY_TO_KIND,
    FrontendKey,
    parse_needs,
    partition,
)
from app.domain.presenters import corridor_out, venue_card_out, venue_out
from app.repositories.protocols import ReferencePoint, VenueRepository
from app.schemas.venues import (
    ConfigOut,
    CorridorOut,
    HealthOut,
    ReferencePointOut,
    SearchOut,
    SportsOut,
    SuburbOut,
    SuburbsOut,
    VenueCardOut,
)

router = APIRouter(prefix="/api/v1")

_TRAILING_POSTCODE = re.compile(r"^(.*?)[\s,]*(\d{4})$")
_LAT_LON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_TRUTHY = {"1", "true", "yes", "on"}

# US2.2 names these three; ``change`` is available on request via ?types=.
DEFAULT_CORRIDOR_TYPES: tuple[FrontendKey, ...] = ("toilet", "parking", "stop")


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut()


@router.get("/config", response_model=ConfigOut)
def config(settings: SettingsDep) -> ConfigOut:
    cfg = settings.search
    return ConfigOut(
        distance_bands_m=cfg.distance_bands_m,
        default_distance_m=cfg.default_distance_m,
        max_results=cfg.max_results,
        source=cfg.source,
    )


@router.get("/sports", response_model=SportsOut)
@router.get("/meta/sports", response_model=SportsOut)
def sports(repo: Repo) -> SportsOut:
    return SportsOut(sports=[s.name for s in repo.list_sports()])


@router.get("/suburbs", response_model=SuburbsOut)
@router.get("/meta/suburbs", response_model=SuburbsOut)
def suburbs(repo: Repo) -> SuburbsOut:
    return SuburbsOut(
        suburbs=[
            SuburbOut(suburb=p.suburb, postcode=p.postcode, label=f"{p.suburb} {p.postcode}")
            for p in repo.list_places()
        ]
    )


def _parse_place(suburb: str | None, postcode: str | None) -> tuple[str | None, str | None]:
    suburb = (suburb or "").strip() or None
    postcode = (postcode or "").strip() or None
    if suburb:
        match = _TRAILING_POSTCODE.match(suburb)
        if match:
            suburb = match.group(1).strip() or None
            postcode = postcode or match.group(2)
    if postcode and not re.fullmatch(r"\d{4}", postcode):
        raise ApiError(422, "validation_error", f"postcode: expected 4 digits, got {postcode!r}")
    return suburb, postcode


def _parse_from(raw: str | None, repo: VenueRepository) -> ReferencePoint | None:
    """``from=Preston 3072`` | ``from=3072`` | ``from=-37.74,145.01`` -> a reference point.

    None when the parameter is absent. A starting point the user did give is
    never silently dropped: if it cannot be resolved, the request fails (422).
    """
    if raw is None or not raw.strip():
        return None
    match = _LAT_LON.match(raw)
    if match:
        lat, lon = float(match.group(1)), float(match.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ApiError(422, "validation_error", "from: expected latitude,longitude in degrees")
        return ReferencePoint("your starting point", lat, lon)
    suburb, postcode = _parse_place(raw, None)
    reference = repo.resolve_reference(suburb, postcode)
    if reference is None:
        raise ApiError(422, "unknown_place", f"No suburb or postcode matching {raw.strip()!r}.")
    return reference


def _parse_limit(raw: str | None, cfg: SearchConfig) -> int:
    if raw is None or not raw.strip():
        return cfg.default_distance_m
    try:
        limit = int(raw)
    except ValueError:
        limit = -1
    if limit not in cfg.distance_bands_m:
        bands = ", ".join(str(b) for b in cfg.distance_bands_m)
        raise ApiError(422, "invalid_distance_band", f"limit must be one of {bands} (metres)")
    return limit


def _parse_facilities(request: Request) -> list[FrontendKey]:
    q = request.query_params
    raw: list[str] = []
    for name in ("needs", "types", "amenities", "facilities"):
        raw.extend(q.getlist(name))
    raw.extend(key for key in FRONTEND_KEYS if (q.get(key) or "").lower() in _TRUTHY)
    try:
        return parse_needs(raw)
    except ValueError as exc:
        keys = ", ".join(FRONTEND_KEYS)
        raise ApiError(422, "validation_error", f"unknown facility {exc}; use {keys}") from exc


@router.get("/search", response_model=SearchOut, response_model_exclude_none=True)
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
        Query(description="Four-digit postcode. Give either suburb or postcode."),
    ] = None,
    needs: Annotated[
        list[str] | None,
        Query(
            description="Facility filters: comma list of toilet, parking, stop, change. "
            "Aliases: types, amenities, facilities, or flag style toilet=true."
        ),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            description="Facility distance limit in metres, one of the bands in /config. "
            "Default 500. Aliases: within, distance_m.",
            examples=[500],
        ),
    ] = None,
) -> SearchOut:
    q = request.query_params
    cfg = settings.search

    sport = (q.get("sport") or "").strip()
    if not sport:
        raise ApiError(422, "validation_error", "sport is required")

    suburb, postcode = _parse_place(q.get("suburb") or q.get("place"), q.get("postcode"))
    if not suburb and not postcode:
        raise ApiError(422, "validation_error", "suburb or postcode is required")

    need_keys = _parse_facilities(request)
    limit_m = _parse_limit(q.get("limit") or q.get("within") or q.get("distance_m"), cfg)

    reference = repo.resolve_reference(suburb, postcode)
    if reference is None:
        typed = " ".join(p for p in (suburb, postcode) if p)
        raise ApiError(422, "unknown_place", f"No suburb or postcode matching {typed!r}.")

    venues = repo.search(sport, reference, cfg.search_radius_m)
    parts = partition(venues, need_keys, limit_m)

    return SearchOut(
        place=" ".join(p for p in (suburb, postcode) if p),
        total=len(venues),
        matched=[venue_out(v) for v in parts.matched[: cfg.max_results]],
        undocumented=[venue_out(v) for v in parts.undocumented[: cfg.max_results]],
        reference_point=ReferencePointOut(
            label=reference.label,
            latitude=reference.latitude,
            longitude=reference.longitude,
        ),
        distance_limit_m=limit_m,
        not_available=parts.not_available,
    )


@router.get("/venues/{venue_id}", response_model=VenueCardOut, response_model_exclude_none=True)
def venue(
    venue_id: str,
    request: Request,
    repo: Repo,
    from_: Annotated[
        str | None,
        Query(
            alias="from",
            description='Optional starting point: "Preston 3072", "3072" or "lat,lon". '
            "Adds distance (km) and reference_point to the card.",
        ),
    ] = None,
) -> VenueCardOut:
    row = repo.get_venue(venue_id)
    if row is None:
        raise ApiError(404, "venue_not_found", f"No venue with id {venue_id!r}.")
    reference = _parse_from(request.query_params.get("from"), repo)
    return venue_card_out(row, reference)


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
            description="Corridor half-width in metres, one of the bands in /config. Default 500."
        ),
    ] = None,
    types: Annotated[
        str | None,
        Query(
            description="Comma list of toilet, parking, stop, change. Default: toilet,parking,stop."
        ),
    ] = None,
) -> CorridorOut:
    """US2.2 / US2.3 - the straight-line corridor (ADR-003). Not a route."""
    row = repo.get_venue(venue_id)
    if row is None:
        raise ApiError(404, "venue_not_found", f"No venue with id {venue_id!r}.")
    q = request.query_params
    origin = _parse_from(q.get("from"), repo)
    if origin is None:
        raise ApiError(
            422,
            "validation_error",
            "from is required: a suburb, postcode or latitude,longitude starting point",
        )
    within = _parse_limit(q.get("within") or q.get("limit"), settings.search)
    keys = _parse_facilities(request) or list(DEFAULT_CORRIDOR_TYPES)
    result = repo.corridor(origin, row, within, [KEY_TO_KIND[key] for key in keys])
    return corridor_out(row, origin, within, keys, result)
