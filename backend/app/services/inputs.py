"""Parsed request inputs handed from the routes to the services.

Every field here is already validated: bands are from ``/config``, dates are
real dates, facility kinds are database names. The one thing a route cannot
settle on its own is a place, because resolving it needs the gazetteer, so a
place travels as ``PlaceInput`` and the location service turns it into a
named ``ReferencePoint``.
"""

from dataclasses import dataclass, field
from datetime import date

from app.domain.facilities import FrontendKey
from app.repositories.protocols import ReferencePoint


@dataclass(frozen=True)
class PlaceInput:
    """What the person gave for a location: a typed place, or a point."""

    suburb: str | None = None
    postcode: str | None = None
    point: ReferencePoint | None = None

    @property
    def typed(self) -> str:
        """The text to echo back in an error, e.g. ``Preston 3072``."""
        return " ".join(p for p in (self.suburb, self.postcode) if p)

    @property
    def given(self) -> bool:
        """Whether anything at all was supplied."""
        return bool(self.suburb or self.postcode or self.point is not None)


@dataclass(frozen=True)
class SearchQuery:
    """``GET /venues/search`` after parsing."""

    sport: str
    place: PlaceInput
    kinds: list[str]
    limit_m: int


@dataclass(frozen=True)
class VenuePageQuery:
    """``GET /venues/{id}`` after parsing."""

    venue_id: str
    origin: PlaceInput | None
    limit_m: int


@dataclass(frozen=True)
class CorridorQuery:
    """``GET /venues/{id}/corridor`` and ``/events/{id}/directions`` after parsing."""

    origin: PlaceInput | None
    within_m: int
    keys: list[FrontendKey]


@dataclass(frozen=True)
class EventListQuery:
    """``GET /events`` after parsing (contract v0.2 section 7.2)."""

    date_from: date
    date_to: date
    place: PlaceInput | None
    within_m: int
    sports: tuple[str, ...] = ()
    venue_id: str | None = None
    status: str = "listable"
    include_past: bool = False
    weekdays: tuple[str, ...] = ()
    time_of_day: tuple[str, ...] = ()
    price: str | None = None
    kinds: list[str] = field(default_factory=list)
    limit_m: int = 500
    page: int = 1
    page_size: int = 50
