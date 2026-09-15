"""Query parameter parsing shared by the routers.

Parsing is deliberately lenient about spelling (the frontend sends
``facilities=accessible_toilet`` and ``distance_m=500``; older pages sent
``needs=toilet`` and ``limit=500``) and strict about values: a band outside
``/config`` or a place the gazetteer does not know is a 422, never a silent
default. A starting point the user did give is never dropped.
"""

import re

from fastapi import Request

from app.core.config import SearchConfig
from app.core.errors import ApiError
from app.domain.facilities import FRONTEND_KEYS, FrontendKey, parse_needs
from app.repositories.protocols import LocationMatch, ReferencePoint, VenueRepository

_TRAILING_POSTCODE = re.compile(r"^(.*?)[\s,]*(\d{4})$")
_LAT_LON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_TRUTHY = {"1", "true", "yes", "on"}

COVERAGE_DESCRIPTION = "SportAble covers sport venues across Victoria."


def parse_place(suburb: str | None, postcode: str | None) -> tuple[str | None, str | None]:
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


def parse_point(raw: str) -> ReferencePoint | None:
    """``-37.74,145.01`` -> a point, or None when the text is not a pair."""
    match = _LAT_LON.match(raw)
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ApiError(422, "validation_error", "expected latitude,longitude in degrees")
    return ReferencePoint("your starting point", lat, lon, kind="point")


def _did_you_mean(match: LocationMatch) -> str:
    labels = [s.label for s in match.suggestions[:3]]
    if not labels:
        return ""
    return " Did you mean " + ", ".join(labels) + "?"


def require_location(
    repo: VenueRepository, suburb: str | None, postcode: str | None, typed: str
) -> ReferencePoint:
    """Resolve or fail with the right code: unknown_place or outside_coverage."""
    match = repo.resolve_location(suburb, postcode)
    if match.outcome == "resolved" and match.reference is not None:
        return match.reference
    if match.outcome == "outside_coverage":
        raise ApiError(
            422,
            "outside_coverage",
            f"{match.matched_label or typed} is outside the area SportAble covers. "
            f"{COVERAGE_DESCRIPTION}",
        )
    raise ApiError(
        422,
        "unknown_place",
        f"No suburb or postcode matching {typed!r}.{_did_you_mean(match)}",
    )


def parse_from(raw: str | None, repo: VenueRepository) -> ReferencePoint | None:
    """``from=Preston 3072`` | ``from=3072`` | ``from=-37.74,145.01`` -> a point.

    None when the parameter is absent. If the person gave one and it cannot
    be resolved, the request fails (422); it is never silently ignored.
    """
    if raw is None or not raw.strip():
        return None
    point = parse_point(raw)
    if point is not None:
        return point
    suburb, postcode = parse_place(raw, None)
    return require_location(repo, suburb, postcode, raw.strip())


def parse_band(raw: str | None, cfg: SearchConfig, default: int | None = None) -> int:
    if raw is None or not raw.strip():
        return default if default is not None else cfg.default_distance_m
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value not in cfg.distance_bands_m:
        bands = ", ".join(str(b) for b in cfg.distance_bands_m)
        raise ApiError(422, "invalid_distance_band", f"distance must be one of {bands} (metres)")
    return value


def parse_facilities(request: Request) -> list[FrontendKey]:
    q = request.query_params
    raw: list[str] = []
    for name in ("needs", "types", "amenities", "facilities"):
        raw.extend(q.getlist(name))
    raw.extend(key for key in FRONTEND_KEYS if (q.get(key) or "").lower() in _TRUTHY)
    try:
        return parse_needs(raw)
    except ValueError as exc:
        raise ApiError(
            422,
            "validation_error",
            f"unknown facility {exc}; use accessible_toilet, accessible_parking, "
            "accessible_transport_stop, accessible_change_facility",
        ) from exc


def first_of(request: Request, *names: str) -> str | None:
    q = request.query_params
    for name in names:
        value = q.get(name)
        if value is not None and value.strip():
            return value
    return None
