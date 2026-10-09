"""Query parameter parsing shared by the routers.

Parsing is deliberately lenient about spelling (the frontend sends
``facilities=accessible_toilet`` and ``distance_m=500``; older pages sent
``needs=toilet`` and ``limit=500``) and strict about values: a band outside
``/config`` is a 422, never a silent default. Everything here is pure: a
place is parsed into a ``PlaceInput`` and resolved by the location service.
"""

import re

from fastapi import Request

from app.core.config import SearchConfig
from app.core.errors import ApiError
from app.domain.facilities import FRONTEND_KEYS, FrontendKey, parse_needs
from app.repositories.protocols import ReferencePoint
from app.services.inputs import PlaceInput

_TRAILING_POSTCODE = re.compile(r"^(.*?)[\s,]*(\d{4})$")
_LAT_LON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_TRUTHY = {"1", "true", "yes", "on"}


def parse_place(suburb: str | None, postcode: str | None) -> tuple[str | None, str | None]:
    """``("Preston 3072", None)`` -> ``("Preston", "3072")``; a bad postcode is a 422."""
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


def parse_origin(raw: str | None) -> PlaceInput | None:
    """``from=Preston 3072`` | ``from=3072`` | ``from=-37.74,145.01`` -> a place input.

    None when the parameter is absent. Resolution happens in the location
    service, which fails the request rather than dropping a place somebody gave.
    """
    if raw is None or not raw.strip():
        return None
    point = parse_point(raw)
    if point is not None:
        return PlaceInput(point=point)
    suburb, postcode = parse_place(raw, None)
    return PlaceInput(suburb=suburb, postcode=postcode)


def place_input(suburb: str | None, postcode: str | None, near: str | None) -> PlaceInput | None:
    """The place from ``suburb`` / ``postcode`` / ``near``; ``near`` wins when given."""
    if near and near.strip():
        return parse_origin(near)
    sub, pc = parse_place(suburb, postcode)
    if not sub and not pc:
        return None
    return PlaceInput(suburb=sub, postcode=pc)


def parse_band(raw: str | None, cfg: SearchConfig, default: int | None = None) -> int:
    """A distance band from ``/config``; anything else is ``invalid_distance_band``."""
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
    """Facility keys from any of the accepted spellings, in request order."""
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
    """The first non-blank query value among the given aliases, or None."""
    q = request.query_params
    for name in names:
        value = q.get(name)
        if value is not None and value.strip():
            return value
    return None
