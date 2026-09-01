"""Row types the API reads, and the repository interface that produces them.

The rows mirror the serving-store schema in ``data/sql/001_schema.sql`` —
``venue``, ``venue_sport``, ``venue_amenity_status`` (+ ``amenity`` + ``source``)
and ``venue_access_chain``. They carry the database's own vocabulary
(``confirmed / not_available / no_published_information``); translation into
what the interface renders happens in ``app.domain``, nowhere else.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class ReferencePoint:
    """Where every venue distance is measured from. AC1.1.3: it must be named."""

    label: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class SportRow:
    name: str
    venue_count: int


@dataclass(frozen=True)
class PlaceRow:
    suburb: str
    postcode: str
    venue_count: int


@dataclass(frozen=True)
class SportEntry:
    sport: str
    surface_type: str | None


@dataclass(frozen=True)
class FacilityRow:
    """One ``venue_amenity_status`` row joined to its nearest amenity and source."""

    kind: str
    status: str
    basis: str
    distance_m: float | None
    amenity_name: str | None = None
    amenity_address: str | None = None
    amenity_lat: float | None = None
    amenity_lon: float | None = None
    opening_hours: str | None = None
    key_required: bool | None = None
    is_inside_venue: bool | None = None
    source_name: str | None = None
    source_updated: date | None = None
    retrieved_at: datetime | None = None


@dataclass(frozen=True)
class ChainRow:
    link: str
    status: str
    basis: str
    detail: str | None


@dataclass(frozen=True)
class VenueRow:
    venue_id: str
    name: str
    suburb: str | None
    postcode: str | None
    lga: str | None
    address: str | None
    latitude: float
    longitude: float
    distance_m: float | None
    sports: tuple[SportEntry, ...]
    facilities: tuple[FacilityRow, ...]
    chain: tuple[ChainRow, ...] = ()
    retrieved_at: datetime | None = None


class VenueRepository(Protocol):
    def list_sports(self) -> list[SportRow]: ...

    def list_places(self) -> list[PlaceRow]: ...

    def resolve_reference(
        self, suburb: str | None, postcode: str | None
    ) -> ReferencePoint | None: ...

    def search(self, sport: str, reference: ReferencePoint, radius_m: int) -> list[VenueRow]: ...

    def get_venue(self, venue_id: str) -> VenueRow | None: ...
