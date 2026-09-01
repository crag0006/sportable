"""Response models — the Iteration 1 contract the frontend is built against.

Shapes follow ``frontend/src/data/Venues.js`` field for field so the interface
needs no change to go live: ``amenities`` is an object keyed ``toilet / parking /
stop / change``, venue ``distance`` is kilometres, amenity ``distance`` is
metres, and the search wrapper is ``total / matched / undocumented / place``.
Extra fields are additive and can be ignored.

There is deliberately no combined score, rating or percentage anywhere (AC2.1.2).
"""

from typing import Literal

from pydantic import BaseModel

State = Literal["confirmed", "recorded", "absent", "none"]
Location = Literal["at_venue", "public_nearby", "unrecorded"]


class HealthOut(BaseModel):
    status: str = "ok"
    service: str = "sportable-api"


class ConfigOut(BaseModel):
    distance_bands_m: list[int]
    default_distance_m: int
    max_results: int
    source: str


class SportsOut(BaseModel):
    sports: list[str]


class SuburbOut(BaseModel):
    suburb: str
    postcode: str
    label: str


class SuburbsOut(BaseModel):
    suburbs: list[SuburbOut]


class AmenityOut(BaseModel):
    state: State
    distance: int | None = None  # metres; present only when state == "recorded"


class ReferencePointOut(BaseModel):
    label: str
    latitude: float
    longitude: float


class VenueOut(BaseModel):
    id: str
    name: str
    suburb: str | None
    postcode: str | None
    sports: list[str]
    surface: str | None
    distance: float  # kilometres from the reference point, one decimal
    amenities: dict[str, AmenityOut]


class SearchOut(BaseModel):
    place: str
    total: int
    matched: list[VenueOut]
    undocumented: list[VenueOut]
    reference_point: ReferencePointOut
    distance_limit_m: int
    not_available: int


class SourceOut(BaseModel):
    name: str
    published_at: str | None = None
    retrieved_at: str | None = None


class AmenityDetailOut(AmenityOut):
    location: Location | None = None
    name: str | None = None
    lat: float | None = None  # position of the nearby public facility, for map pins
    lon: float | None = None
    opening_hours: str | None = None  # None = the source does not record it
    mlak: bool | None = None  # None = the source does not record it
    source: SourceOut | None = None


class UnpublishedOut(BaseModel):
    key: str
    label: str
    reason: str


class VenueCardOut(BaseModel):
    id: str
    name: str
    address: str | None
    suburb: str | None
    postcode: str | None
    lga: str | None
    lat: float
    lon: float
    sports: list[str]
    surface: str | None
    amenities: dict[str, AmenityDetailOut]
    unpublished: list[UnpublishedOut]
    last_updated: str | None
