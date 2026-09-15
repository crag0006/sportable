"""Response models for search, the venue page and the corridor.

Contract v0.2 shapes, with the v0.1 fields still present during the switch
(contract §11): a page can move one field at a time and nothing breaks the day
this lands. Every v0.1 field is marked ``deprecated`` so Swagger shows which
half of the object goes away at the Iteration 2 freeze.

There is deliberately no combined score, rating or percentage anywhere
(AC2.1.2, AC3.1.3).
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import (
    FacilityOut,
    ReferencePointOut,
    SourceRefOut,
    VenueSummaryOut,
)

# ---------------------------------------------------------------- v0.1 bits
State = Literal["confirmed", "recorded", "absent", "none"]
Location = Literal["at_venue", "public_nearby", "unrecorded"]


class HealthOut(BaseModel):
    status: str = "ok"
    service: str = "sportable-api"


class EventsConfigOut(BaseModel):
    default_window_days: int
    max_window_days: int
    page_size: int


class ConfigOut(BaseModel):
    distance_bands_m: list[int]
    default_distance_m: int
    search_radius_m: int
    corridor_default_m: int
    max_results: int
    events: EventsConfigOut
    timezone: str
    default_stale_after_days: int
    source: str


class SportOut(BaseModel):
    name: str
    venue_count: int
    event_count: int = 0


class SportsOut(BaseModel):
    sports: list[SportOut]


class SuburbOut(BaseModel):
    suburb: str
    postcode: str
    label: str


class SuburbsOut(BaseModel):
    suburbs: list[SuburbOut]


class AmenityOut(BaseModel):
    state: State
    distance: int | None = None  # metres; present only when state == "recorded"


class SourceOut(BaseModel):
    """v0.1 provenance. v0.2 uses ``SourceRefOut`` (common)."""

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


# ------------------------------------------------------------------ search
class SearchVenueOut(VenueSummaryOut):
    """One search result: the v0.2 summary plus the four tiles, with the v0.1
    fields alongside until the switch."""

    distance_m: int
    facilities: list[FacilityOut]
    # v0.1
    distance: float = Field(deprecated=True, description="Kilometres. Use distance_m.")
    surface: str | None = Field(default=None, deprecated=True, description="Use surface_types.")
    amenities: dict[str, AmenityOut] = Field(deprecated=True, description="Use facilities.")


class VenueOut(SearchVenueOut):
    """Alias kept for the v0.1 import path."""


class CountsOut(BaseModel):
    total_for_sport: int
    matched: int
    undocumented: int
    not_available: int


class GroupOut(BaseModel):
    label: str
    count: int
    results: list[SearchVenueOut]


class SearchOut(BaseModel):
    sport: str
    reference_point: ReferencePointOut
    distance_limit_m: int
    search_radius_m: int
    facilities_requested: list[str]
    counts: CountsOut
    results: list[SearchVenueOut]
    undocumented_group: GroupOut
    not_available_group: GroupOut
    retrieved_at: str | None = None
    # v0.1
    place: str = Field(deprecated=True, description="Use reference_point.label.")
    total: int = Field(deprecated=True, description="Use counts.total_for_sport.")
    matched: list[SearchVenueOut] = Field(deprecated=True, description="Use results.")
    undocumented: list[SearchVenueOut] = Field(
        deprecated=True, description="Use undocumented_group.results."
    )
    not_available: int = Field(deprecated=True, description="Use counts.not_available.")


# -------------------------------------------------------------- venue page
class AccessLinkOut(BaseModel):
    link: str
    label: str
    facility_type: str | None = None
    status: str
    summary: str


class LimitItemOut(BaseModel):
    topic: str
    reason: str


class LimitsOut(BaseModel):
    heading: str
    items: list[LimitItemOut]


class UpcomingEventsOut(BaseModel):
    count: int
    next_starts_at: str | None = None
    href: str | None = None


class VenueCardOut(VenueSummaryOut):
    ownership: str | None = None
    purpose: str | None = None
    changeroom_description: str | None = None
    facilities: list[FacilityOut]
    access_chain: list[AccessLinkOut]
    limits: LimitsOut
    sources: list[SourceRefOut]
    upcoming_events: UpcomingEventsOut
    last_updated: str | None = None
    # Only when the request carried ?from=
    distance_m: int | None = None
    reference_point: ReferencePointOut | None = None
    # v0.1
    lat: float = Field(deprecated=True, description="Use latitude.")
    lon: float = Field(deprecated=True, description="Use longitude.")
    surface: str | None = Field(default=None, deprecated=True, description="Use surface_types.")
    amenities: dict[str, AmenityDetailOut] = Field(deprecated=True, description="Use facilities.")
    unpublished: list[UnpublishedOut] = Field(
        deprecated=True, description="Use access_chain and limits."
    )
    distance: float | None = Field(
        default=None, deprecated=True, description="Kilometres. Use distance_m."
    )


# ---------------------------------------------------------------- corridor
CorridorTypeStatus = Literal["found", "none_within", "no_data"]


class CorridorVenueOut(BaseModel):
    id: str
    name: str
    address: str | None
    latitude: float
    longitude: float
    href: str
    # v0.1
    lat: float = Field(deprecated=True, description="Use latitude.")
    lon: float = Field(deprecated=True, description="Use longitude.")


class CorridorPathOut(BaseModel):
    kind: Literal["straight_line", "routed"] = "straight_line"
    length_m: int  # straight-line metres, NOT a travel distance
    within_m: int  # the corridor half-width applied
    coordinates: list[list[float]]  # [[lat, lon], [lat, lon]]


class CorridorTypeOut(BaseModel):
    type: str
    label: str
    count: int
    status: CorridorTypeStatus  # found | none_within | no_data - different copy each
    message: str | None = None


class CorridorFacilityOut(BaseModel):
    seq: int  # 1-based position in travel order (AC2.3.2)
    type: str
    name: str | None = None
    address: str | None = None
    latitude: float
    longitude: float
    distance_from_path_m: int
    along_path_m: int
    opening_hours: str | None = None
    opening_hours_unrecorded: bool = False
    key_required: bool | None = None
    key_requirement_unrecorded: bool = False
    source: SourceRefOut | None = None
    # v0.1
    lat: float = Field(deprecated=True, description="Use latitude.")
    lon: float = Field(deprecated=True, description="Use longitude.")
    mlak: bool | None = Field(default=None, deprecated=True, description="Use key_required.")


class CorridorOut(BaseModel):
    venue: CorridorVenueOut
    origin: ReferencePointOut
    path: CorridorPathOut
    types: list[CorridorTypeOut]
    facilities: list[CorridorFacilityOut]
    checked: list[str]
    not_checked: list[str]
    disclaimer: str
    retrieved_at: str | None = None
