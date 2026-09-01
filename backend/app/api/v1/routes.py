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
"""

import re

from fastapi import APIRouter, Request

from app.api.deps import Repo, SettingsDep
from app.core.config import SearchConfig
from app.core.errors import ApiError
from app.domain.facilities import FRONTEND_KEYS, FrontendKey, parse_needs, partition
from app.domain.presenters import venue_card_out, venue_out
from app.schemas.venues import (
    ConfigOut,
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
_TRUTHY = {"1", "true", "yes", "on"}


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
    for name in ("needs", "amenities", "facilities"):
        raw.extend(q.getlist(name))
    raw.extend(key for key in FRONTEND_KEYS if (q.get(key) or "").lower() in _TRUTHY)
    try:
        return parse_needs(raw)
    except ValueError as exc:
        keys = ", ".join(FRONTEND_KEYS)
        raise ApiError(422, "validation_error", f"unknown facility {exc}; use {keys}") from exc


@router.get("/search", response_model=SearchOut, response_model_exclude_none=True)
@router.get("/venues/search", response_model=SearchOut, response_model_exclude_none=True)
def search(request: Request, repo: Repo, settings: SettingsDep) -> SearchOut:
    q = request.query_params
    cfg = settings.search

    sport = (q.get("sport") or "").strip()
    if not sport:
        raise ApiError(422, "validation_error", "sport is required")

    suburb, postcode = _parse_place(q.get("suburb") or q.get("place"), q.get("postcode"))
    if not suburb and not postcode:
        raise ApiError(422, "validation_error", "suburb or postcode is required")

    needs = _parse_facilities(request)
    limit = _parse_limit(q.get("limit") or q.get("within") or q.get("distance_m"), cfg)

    reference = repo.resolve_reference(suburb, postcode)
    if reference is None:
        typed = " ".join(p for p in (suburb, postcode) if p)
        raise ApiError(422, "unknown_place", f"No suburb or postcode matching {typed!r}.")

    venues = repo.search(sport, reference, cfg.search_radius_m)
    parts = partition(venues, needs, limit)

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
        distance_limit_m=limit,
        not_available=parts.not_available,
    )


@router.get("/venues/{venue_id}", response_model=VenueCardOut, response_model_exclude_none=True)
def venue(venue_id: str, repo: Repo) -> VenueCardOut:
    row = repo.get_venue(venue_id)
    if row is None:
        raise ApiError(404, "venue_not_found", f"No venue with id {venue_id!r}.")
    return venue_card_out(row)
