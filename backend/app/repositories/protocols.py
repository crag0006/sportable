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
    """Where every venue distance is measured from. AC1.1.3: it must be named.

    ``kind`` is ``suburb``, ``postcode`` or ``point`` (a lat,lon the user gave);
    ``code`` is the ABS code when the point came from the gazetteer.
    """

    label: str
    latitude: float
    longitude: float
    kind: str = "suburb"
    code: str | None = None


@dataclass(frozen=True)
class SportRow:
    name: str
    venue_count: int
    event_count: int = 0


@dataclass(frozen=True)
class SourceRow:
    """One row of the source register plus its latest load run (v0.2 §3.5)."""

    source_id: str
    name: str
    publisher: str | None
    licence_name: str | None
    licence_url: str | None
    attribution_text: str | None
    landing_page: str | None
    publisher_scope: str | None
    publisher_last_updated: date | None
    stale_after_days: int | None = None
    retrieved_at: datetime | None = None
    rows_loaded: int | None = None
    outcome: str | None = None


@dataclass(frozen=True)
class LocationSuggestion:
    label: str
    kind: str
    code: str | None = None


@dataclass(frozen=True)
class LocationMatch:
    """What the gazetteer said about a typed place (v0.2 §3.4).

    ``outcome`` is ``resolved``, ``outside_coverage`` or ``unresolved``; an
    empty answer on its own is forbidden (AC1.1.4), so ``unresolved`` always
    carries suggestions when the gazetteer has anything similar.
    """

    outcome: str
    reference: ReferencePoint | None = None
    matched_label: str | None = None
    matched_kind: str | None = None
    suggestions: tuple[LocationSuggestion, ...] = ()


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

    # v0.2 - the columns of ``venue_facility_detail`` (data/sql/005 + 007).
    # Every one of these has a default so the v0.1 rows above keep working.
    source_id: str | None = None
    stale_after_days: int | None = None
    within_250m: bool | None = None
    within_500m: bool | None = None
    within_1000m: bool | None = None
    location_relative_to_venue: str | None = None
    opening_hours_unrecorded: bool | None = None
    key_requirement_unrecorded: bool | None = None
    mlak_24h: bool | None = None
    payment_required: bool | None = None
    access_note: str | None = None
    changing_places: bool | None = None
    has_shower: bool | None = None
    ambulant: bool | None = None
    left_hand_transfer: bool | None = None
    right_hand_transfer: bool | None = None
    transport_mode: str | None = None
    # A separately published description attached to a publisher-confirmed
    # status (migration 007). Its source is not the status's source.
    detail_amenity_id: str | None = None
    detail_source_id: str | None = None
    detail_source_name: str | None = None
    detail_source_updated: date | None = None
    detail_distance_m: float | None = None
    # The nearby public alternative to a published absence (migration 007).
    alternative_amenity_id: str | None = None
    alternative_name: str | None = None
    alternative_distance_m: float | None = None
    alternative_lat: float | None = None
    alternative_lon: float | None = None
    alternative_opening_hours: str | None = None
    alternative_key_required: bool | None = None
    alternative_source_id: str | None = None
    alternative_source_name: str | None = None
    alternative_source_updated: date | None = None


@dataclass(frozen=True)
class CorridorFacilityRow:
    """One amenity inside the straight-line corridor origin -> venue (ADR-003)."""

    kind: str
    name: str | None
    address: str | None
    lat: float
    lon: float
    distance_from_path_m: float
    fraction: float  # 0..1 along the line - the travel order
    opening_hours: str | None = None
    key_required: bool | None = None
    source_name: str | None = None
    source_updated: date | None = None
    retrieved_at: datetime | None = None


@dataclass(frozen=True)
class CorridorResult:
    """Corridor rows plus how many amenities of each kind exist at all.

    ``totals`` separates "nothing within the corridor" from "no dataset
    loaded" - the two must never read the same (unknown is never a no).
    """

    facilities: tuple[CorridorFacilityRow, ...]
    totals: dict[str, int]


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
    # v0.2 - carried from venue_card for the venue page.
    surface_types: tuple[str, ...] = ()
    ownership: str | None = None
    purpose: str | None = None
    changeroom_description: str | None = None
    lga_code: str | None = None


@dataclass(frozen=True)
class EventRow:
    """One ``event`` row (data/sql/008) joined to its source and, when matched,
    its venue with the four facility rows."""

    event_id: str
    source_id: str
    kind: str  # fixture | program
    title: str
    status: str
    external_url: str
    retrieved_at: datetime
    sport: str | None = None
    sport_raw: str | None = None
    competition: str | None = None
    season: str | None = None
    grade: str | None = None
    round: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    description: str | None = None
    organisation: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: str = "Australia/Melbourne"
    weekdays: tuple[str, ...] = ()
    time_of_day: tuple[str, ...] = ()
    price: str | None = None
    age_ranges: tuple[str, ...] = ()
    access_needs: tuple[str, ...] = ()
    registration_url: str | None = None
    venue_external_id: str | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    venue_suburb: str | None = None
    venue_postcode: str | None = None
    venue_lat: float | None = None
    venue_lon: float | None = None
    venue_id: str | None = None
    venue_match_basis: str = "none"
    venue_match_distance_m: float | None = None
    publisher_updated_at: datetime | None = None
    source_name: str | None = None
    source_attribution: str | None = None
    source_publisher_last_updated: date | None = None
    source_stale_after_days: int | None = None
    distance_m: float | None = None
    venue: VenueRow | None = None


@dataclass(frozen=True)
class EventFilters:
    """What /events was asked for (contract v0.2 section 7.2)."""

    date_from: date
    date_to: date
    now: datetime
    sports: tuple[str, ...] = ()
    reference: ReferencePoint | None = None
    within_m: int = 10_000
    venue_id: str | None = None
    status: str = "listable"  # listable | all
    include_past: bool = False
    weekdays: tuple[str, ...] = ()
    time_of_day: tuple[str, ...] = ()
    price: str | None = None
    limit: int = 1000


@dataclass(frozen=True)
class EventSportRow:
    name: str
    event_count: int


@dataclass(frozen=True)
class UpcomingRow:
    count: int
    next_starts_at: datetime | None


class VenueRepository(Protocol):
    def list_sports(self, q: str | None = None) -> list[SportRow]: ...

    def list_places(self) -> list[PlaceRow]: ...

    def resolve_reference(
        self, suburb: str | None, postcode: str | None
    ) -> ReferencePoint | None: ...

    def resolve_location(self, suburb: str | None, postcode: str | None) -> LocationMatch: ...

    def list_sources(self) -> list[SourceRow]: ...

    def list_events(self, filters: EventFilters) -> list[EventRow]: ...

    def get_event(self, event_id: str) -> EventRow | None: ...

    def event_sports(
        self, date_from: date, date_to: date, now: datetime
    ) -> list[EventSportRow]: ...

    def upcoming_events(self, venue_id: str, now: datetime) -> UpcomingRow: ...

    def search(self, sport: str, reference: ReferencePoint, radius_m: int) -> list[VenueRow]: ...

    def get_venue(self, venue_id: str) -> VenueRow | None: ...

    def corridor(
        self, origin: ReferencePoint, venue: VenueRow, within_m: int, kinds: list[str]
    ) -> CorridorResult: ...
