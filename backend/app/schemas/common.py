"""Shared response models for API contract v0.2.

These are the objects that appear in more than one endpoint: the provenance
reference (§2.1), the facility tile (§2.2), the reference point (§2.3) and
the venue summary (§2.4). Defining them once is what keeps search results,
the venue page, events and assistant answers from drifting apart.
"""

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["confirmed", "not_available", "no_published_information"]
Basis = Literal["publisher_attribute", "spatial_proximity", "not_published"]
Display = Literal[
    "at_venue",
    "nearby",
    "beyond_limit",
    "not_available",
    "not_available_alternative",
    "no_published_information",
]
Kind = Literal[
    "accessible_toilet",
    "accessible_parking",
    "accessible_transport_stop",
    "accessible_change_facility",
]


class SourceRefOut(BaseModel):
    """§2.1 - the inline provenance object on every fact."""

    id: str | None = None
    name: str
    publisher_last_updated: str | None = None
    retrieved_at: str | None = None
    possibly_out_of_date: bool
    stale_after_days: int


class DetailSourceOut(SourceRefOut):
    """The publisher of an attached description, with how far away it sits."""

    distance_m: int | None = None


class FacilityDetailOut(BaseModel):
    """Venue page only (§5). ``None`` on an attribute means the source recorded
    nothing; the ``*_unrecorded`` flags say so explicitly (AC2.1.4)."""

    location_relative_to_venue: str
    name: str | None = None
    address: str | None = None
    opening_hours: str | None = None
    opening_hours_unrecorded: bool = False
    key_required: bool | None = None
    key_requirement_unrecorded: bool = False
    mlak_24h: bool | None = None
    payment_required: bool | None = None
    left_hand_transfer: bool | None = None
    right_hand_transfer: bool | None = None
    ambulant: bool | None = None
    changing_places: bool | None = None
    has_shower: bool | None = None
    access_note: str | None = None
    transport_mode: str | None = None
    detail_source: DetailSourceOut | None = None
    latitude: float | None = None
    longitude: float | None = None


class AlternativeOut(BaseModel):
    """The nearby public facility offered under a red tile."""

    name: str | None = None
    distance_m: int
    opening_hours: str | None = None
    key_required: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    source: SourceRefOut | None = None


class FacilityOut(BaseModel):
    """§2.2 - one tile. Always four per venue, always in the contract order."""

    type: Kind
    label: str
    status: Status
    basis: Basis
    display: Display
    distance_m: int | None = None
    distance_limit_m: int
    message: str
    source: SourceRefOut | None = None
    alternative: AlternativeOut | None = None
    detail: FacilityDetailOut | None = None


class ReferencePointOut(BaseModel):
    """§2.3 - where distances are measured from. ``label`` is ready-made copy."""

    label: str
    kind: Literal["suburb", "postcode", "point"] = "suburb"
    code: str | None = None
    latitude: float
    longitude: float


class VenueSummaryOut(BaseModel):
    """§2.4 - the identity block shared by search results and events."""

    id: str
    name: str
    address: str | None = None
    suburb: str | None = None
    postcode: str | None = None
    lga: str | None = None
    latitude: float
    longitude: float
    sports: list[str] = Field(default_factory=list)
    surface_types: list[str] = Field(default_factory=list)
    href: str
