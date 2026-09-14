"""An in-memory repository so the API can be tested without PostGIS.

The rows mirror what the loader and status builder write, including the two
edge cases the Data team called out: a facility confirmed at the venue itself
(no distance) and a nearest amenity beyond 1 km (distance kept, status
``no_published_information``).
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.api.deps import get_now, get_repository
from app.main import app
from app.repositories.protocols import (
    ChainRow,
    CorridorFacilityRow,
    CorridorResult,
    EventFilters,
    EventRow,
    EventSportRow,
    FacilityRow,
    LocationMatch,
    LocationSuggestion,
    PlaceRow,
    ReferencePoint,
    SourceRow,
    SportEntry,
    SportRow,
    UpcomingRow,
    VenueRow,
)
from fastapi.testclient import TestClient

RETRIEVED = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)
TOILET_MAP = ("National Public Toilet Map", date(2026, 7, 14))
FACILITIES = ("Sport and Recreation Victoria facilities list", date(2026, 8, 22))


def _row(
    kind: str,
    status: str,
    basis: str,
    distance_m: float | None,
    source: tuple[str, date] | None = TOILET_MAP,
    **detail: object,
) -> FacilityRow:
    return FacilityRow(
        kind=kind,
        status=status,
        basis=basis,
        distance_m=distance_m,
        source_name=source[0] if source else None,
        source_updated=source[1] if source else None,
        retrieved_at=RETRIEVED if source else None,
        **detail,  # type: ignore[arg-type]
    )


PRESTON = ReferencePoint("the centre of Preston 3072", -37.7412, 145.0006)

VENUES: list[VenueRow] = [
    VenueRow(
        venue_id="10432",
        name="Preston City Oval",
        suburb="Preston",
        postcode="3072",
        lga="Darebin",
        address="121 Cramer Street, Preston VIC 3072",
        latitude=-37.7401,
        longitude=145.0093,
        distance_m=640.0,
        sports=(SportEntry("Basketball", "Indoor sprung timber"), SportEntry("Netball", None)),
        facilities=(
            _row(
                "accessible_toilet",
                "confirmed",
                "spatial_proximity",
                45.0,
                amenity_name="Preston City Oval Toilets",
                amenity_lat=-37.7398,
                amenity_lon=145.0101,
                opening_hours="6:00am - 9:00pm",
                key_required=True,
                is_inside_venue=False,
            ),
            # Venue-confirmed, but the status builder also attached the nearest
            # public bay (120 m). The API must present this as "at the venue".
            _row(
                "accessible_parking",
                "confirmed",
                "publisher_attribute",
                120.0,
                FACILITIES,
                amenity_name="Cramer St bay",
                amenity_lat=-37.7412,
                amenity_lon=145.0080,
                opening_hours="24 hours",
                source_id="DS-01",
                detail_amenity_id="DS-04:bay-7",
                detail_source_id="DS-04",
                detail_source_name="Accessible Parking Locations, City of Melbourne",
                detail_source_updated=date(2026, 6, 30),
                detail_distance_m=18.0,
            ),
            _row(
                "accessible_transport_stop", "no_published_information", "not_published", None, None
            ),
            _row(
                "accessible_change_facility",
                "no_published_information",
                "spatial_proximity",
                1340.0,
            ),
        ),
        chain=(
            ChainRow("enter", "no_published_information", "not_published", "Not published."),
            ChainRow("play", "no_published_information", "not_published", None),
        ),
        retrieved_at=RETRIEVED,
    ),
    VenueRow(
        venue_id="11876",
        name="Northcote Aquatic and Recreation Centre",
        suburb="Northcote",
        postcode="3070",
        lga="Darebin",
        address="7 Mayer Park, Northcote VIC 3070",
        latitude=-37.7688,
        longitude=144.9982,
        distance_m=1820.0,
        sports=(SportEntry("Basketball", "Indoor sprung timber"), SportEntry("Swimming", "Pool")),
        facilities=(
            _row("accessible_toilet", "confirmed", "spatial_proximity", 15.0),
            _row("accessible_parking", "confirmed", "spatial_proximity", 60.0),
            _row("accessible_transport_stop", "confirmed", "spatial_proximity", 210.0),
            _row("accessible_change_facility", "confirmed", "spatial_proximity", 15.0),
        ),
        retrieved_at=RETRIEVED,
    ),
    VenueRow(
        venue_id="10088",
        name="Reservoir Leisure Centre",
        suburb="Reservoir",
        postcode="3073",
        lga="Darebin",
        address="2 Cheddar Road, Reservoir VIC 3073",
        latitude=-37.7160,
        longitude=145.0035,
        distance_m=2940.0,
        sports=(SportEntry("Basketball", None),),
        facilities=(
            _row(
                "accessible_toilet",
                "not_available",
                "publisher_attribute",
                None,
                FACILITIES,
                source_id="DS-01",
                alternative_amenity_id="DS-02:9981:toilet",
                alternative_name="Edwardes Lake Park toilets",
                alternative_distance_m=158.0,
                alternative_lat=-37.7150,
                alternative_lon=145.0050,
                alternative_opening_hours="24 hours",
                alternative_key_required=False,
                alternative_source_id="DS-02",
                alternative_source_name=TOILET_MAP[0],
                alternative_source_updated=TOILET_MAP[1],
            ),
            _row("accessible_parking", "no_published_information", "spatial_proximity", None),
            _row("accessible_transport_stop", "confirmed", "spatial_proximity", 540.0),
            _row(
                "accessible_change_facility", "no_published_information", "spatial_proximity", None
            ),
        ),
        retrieved_at=RETRIEVED,
    ),
]


# The corridor Preston -> Preston City Oval: two toilets and a parking bay at
# fixed fractions along the line. Transport stops exist in no dataset (GTFS
# pending), change facilities exist but none near this line.
CORRIDOR_TOTALS = {
    "accessible_toilet": 5,
    "accessible_parking": 3,
    "accessible_transport_stop": 0,
    "accessible_change_facility": 2,
}

CORRIDOR_ROWS: list[CorridorFacilityRow] = [
    CorridorFacilityRow(
        kind="accessible_toilet",
        name="Gower St toilets",
        address="1 Gower St, Preston",
        lat=-37.7410,
        lon=145.0020,
        distance_from_path_m=90.0,
        fraction=0.2,
        opening_hours="24 hours",
        key_required=False,
        source_name=TOILET_MAP[0],
        source_updated=TOILET_MAP[1],
        retrieved_at=RETRIEVED,
    ),
    CorridorFacilityRow(
        kind="accessible_parking",
        name="High St bay",
        address=None,
        lat=-37.7405,
        lon=145.0060,
        distance_from_path_m=420.0,
        fraction=0.55,
        source_name="On-street Car Park Bay Restrictions",
        source_updated=date(2026, 6, 30),
        retrieved_at=RETRIEVED,
    ),
    CorridorFacilityRow(
        kind="accessible_toilet",
        name="Northland",
        address=None,
        lat=-37.7396,
        lon=145.0335,
        distance_from_path_m=800.0,
        fraction=0.8,
        key_required=True,
        source_name=TOILET_MAP[0],
        source_updated=TOILET_MAP[1],
        retrieved_at=RETRIEVED,
    ),
]


SOURCES: list[SourceRow] = [
    SourceRow(
        source_id="DS-01",
        name=FACILITIES[0],
        publisher="Sport and Recreation Victoria",
        licence_name="Creative Commons Attribution 4.0 International",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        attribution_text="Sport and Recreational Facilities List, Sport and Recreation Victoria",
        landing_page="https://discover.data.vic.gov.au/dataset/sport-and-recreational-facilities-list",
        publisher_scope="statewide",
        publisher_last_updated=FACILITIES[1],
        retrieved_at=RETRIEVED,
        rows_loaded=2153,
        outcome="landed",
    ),
    SourceRow(
        source_id="DS-02",
        name=TOILET_MAP[0],
        publisher="Australian Government Department of Health",
        licence_name="Creative Commons Attribution 3.0 Australia",
        licence_url="https://creativecommons.org/licenses/by/3.0/au/",
        attribution_text="National Public Toilet Map",
        landing_page="https://toiletmap.gov.au/",
        publisher_scope="national",
        publisher_last_updated=date(2022, 1, 12),
        retrieved_at=RETRIEVED,
        rows_loaded=3718,
        outcome="landed",
    ),
    SourceRow(
        source_id="DS-05",
        name="openrouteservice",
        publisher="HeiGIT",
        licence_name="Creative Commons Attribution-ShareAlike 4.0 International",
        licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
        attribution_text="Routing by openrouteservice, OpenStreetMap contributors",
        landing_page="https://openrouteservice.org/",
        publisher_scope="global",
        publisher_last_updated=None,
    ),
]


def _venue(venue_id: str) -> VenueRow:
    return next(v for v in VENUES if v.venue_id == venue_id)


# Two fixtures and two programs. NEXT_SAT is relative to the fake's "now" so
# the window logic is exercised against a real date rather than a frozen one.
NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
NEXT_SAT = (NOW + timedelta(days=(5 - NOW.weekday()) % 7 or 7)).replace(hour=9, minute=30)
EVENTS: list[EventRow] = [
    EventRow(
        event_id="fx-1",
        source_id="DS-10",
        kind="fixture",
        title="Preston Bullets v Northcote Giants",
        status="UPCOMING",
        external_url="https://www.playhq.com/x/fx-1",
        retrieved_at=NOW,
        sport="Basketball",
        competition="Big V Championship Men",
        grade="Championship Men",
        round="Round 12",
        home_team="Preston Bullets",
        away_team="Northcote Giants",
        starts_at=NEXT_SAT,
        venue_name="Preston City Oval",
        venue_address="121 Cramer Street, Preston VIC 3072",
        venue_lat=-37.7401,
        venue_lon=145.0093,
        venue_id="10432",
        venue_match_basis="name_and_distance",
        venue_match_distance_m=12.0,
        source_name="PlayHQ",
        source_attribution="Fixture data provided by PlayHQ",
        source_stale_after_days=2,
        distance_m=640.0,
        venue=_venue("10432"),
    ),
    EventRow(
        event_id="fx-cancelled",
        source_id="DS-10",
        kind="fixture",
        title="Reservoir Rebels v Bundoora Bears",
        status="CANCELLED",
        external_url="https://www.playhq.com/x/fx-cancelled",
        retrieved_at=NOW,
        sport="Basketball",
        starts_at=NEXT_SAT + timedelta(hours=2),
        venue_name="Reservoir Leisure Centre",
        venue_id="10088",
        venue_match_basis="name_and_distance",
        source_name="PlayHQ",
        source_attribution="Fixture data provided by PlayHQ",
        venue=_venue("10088"),
    ),
    EventRow(
        event_id="aaaplay:25089",
        source_id="DS-09",
        kind="program",
        title="PlayOn",
        status="ACTIVE",
        external_url="https://aaaplay.org.au/activity/playon/",
        retrieved_at=NOW,
        sport="Basketball",
        sport_raw="Basketball",
        organisation="PlayOn Victoria",
        weekdays=("wednesday",),
        time_of_day=("evening",),
        price="free",
        age_ranges=("Adults (26+)",),
        access_needs=(),
        registration_url="https://forms.example/playon",
        venue_name="Northcote Aquatic and Recreation Centre",
        venue_id="11876",
        venue_match_basis="name_and_distance",
        venue_match_distance_m=40.0,
        source_name="AAA Play activity finder",
        source_attribution="Activity and facility listings from AAA Play, Reclink Australia",
        source_publisher_last_updated=date(2026, 9, 10),
        distance_m=1820.0,
        venue=_venue("11876"),
    ),
    EventRow(
        event_id="aaaplay:25086",
        source_id="DS-09",
        kind="program",
        title="Power 2 Pedal Program",
        status="ACTIVE",
        external_url="https://aaaplay.org.au/activity/power-2-pedal-program-geelong/",
        retrieved_at=NOW,
        sport=None,
        sport_raw="Bike riding, BMX & cycling",
        weekdays=(),
        time_of_day=("afternoon",),
        price="paid",
        venue_name="Leisure Networks",
        venue_address="Geelong VIC",
        venue_lat=-38.1712,
        venue_lon=144.3513,
        venue_match_basis="none",
        source_name="AAA Play activity finder",
        source_attribution="Activity and facility listings from AAA Play, Reclink Australia",
        source_publisher_last_updated=date(2026, 9, 10),
        venue=None,
    ),
]


def _listable(e: EventRow, f: EventFilters) -> bool:
    if f.status == "all":
        return True
    if e.kind == "program":
        return e.status == "ACTIVE"
    return e.status in ("UPCOMING", "PENDING") and (
        f.include_past or (e.starts_at or f.now) > f.now
    )


class FakeRepository:
    def list_events(self, f: EventFilters) -> list[EventRow]:
        out: list[EventRow] = []
        for e in EVENTS:
            if not _listable(e, f):
                continue
            if (
                e.kind == "fixture"
                and e.starts_at is not None
                and not (f.date_from <= e.starts_at.date() <= f.date_to)
            ):
                continue
            if f.sports and (e.sport or e.sport_raw or "").lower() not in {
                s.lower() for s in f.sports
            }:
                continue
            if f.venue_id and e.venue_id != f.venue_id:
                continue
            if f.weekdays and not (set(f.weekdays) & set(e.weekdays)):
                continue
            if f.price and e.price != f.price:
                continue
            if f.reference is not None and e.distance_m is None:
                continue
            out.append(e)
        return out

    def get_event(self, event_id: str) -> EventRow | None:
        return next((e for e in EVENTS if e.event_id == event_id), None)

    def event_sports(self, date_from: date, date_to: date, now: datetime) -> list[EventSportRow]:
        return [EventSportRow("Basketball", 2), EventSportRow("Bike riding, BMX & cycling", 1)]

    def upcoming_events(self, venue_id: str, now: datetime) -> UpcomingRow:
        rows = [e for e in EVENTS if e.venue_id == venue_id and e.status in ("UPCOMING", "ACTIVE")]
        nxt = min((e.starts_at for e in rows if e.starts_at is not None), default=None)
        return UpcomingRow(len(rows), nxt)

    def list_sports(self, q: str | None = None) -> list[SportRow]:
        rows = [SportRow("Basketball", 3), SportRow("Netball", 1), SportRow("Swimming", 1)]
        if q:
            rows = [r for r in rows if q.lower() in r.name.lower()]
        return rows

    def resolve_location(self, suburb: str | None, postcode: str | None) -> LocationMatch:
        name = (suburb or "").lower()
        if name == "preston" or (not suburb and postcode == "3072"):
            if not suburb:
                reference = ReferencePoint(
                    "the centre of postcode 3072",
                    PRESTON.latitude,
                    PRESTON.longitude,
                    kind="postcode",
                    code="3072",
                )
            else:
                label = (
                    "the centre of Preston 3072" if postcode == "3072" else "the centre of Preston"
                )
                reference = ReferencePoint(
                    label, PRESTON.latitude, PRESTON.longitude, kind="suburb", code="SAL21713"
                )
            return LocationMatch("resolved", reference, "Preston", reference.kind)
        if name == "hobart":
            return LocationMatch("outside_coverage", None, "Hobart", "suburb")
        if name.startswith("prest"):
            return LocationMatch(
                "unresolved",
                suggestions=(LocationSuggestion("Preston 3072", "suburb", "SAL21713"),),
            )
        return LocationMatch("unresolved")

    def list_sources(self) -> list[SourceRow]:
        return SOURCES

    def list_places(self) -> list[PlaceRow]:
        return [PlaceRow("Northcote", "3070", 1), PlaceRow("Preston", "3072", 1)]

    def resolve_reference(self, suburb: str | None, postcode: str | None) -> ReferencePoint | None:
        return self.resolve_location(suburb, postcode).reference

    def search(self, sport: str, reference: ReferencePoint, radius_m: int) -> list[VenueRow]:
        return [v for v in VENUES if any(s.sport.lower() == sport.lower() for s in v.sports)]

    def get_venue(self, venue_id: str) -> VenueRow | None:
        return next((v for v in VENUES if v.venue_id == venue_id), None)

    def corridor(
        self, origin: ReferencePoint, venue: VenueRow, within_m: int, kinds: list[str]
    ) -> CorridorResult:
        rows = sorted(
            (r for r in CORRIDOR_ROWS if r.kind in kinds and r.distance_from_path_m <= within_m),
            key=lambda r: r.fraction,
        )
        return CorridorResult(
            facilities=tuple(rows),
            totals={kind: CORRIDOR_TOTALS.get(kind, 0) for kind in kinds},
        )


@pytest.fixture
def venues() -> list[VenueRow]:
    return VENUES


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = FakeRepository
    app.dependency_overrides[get_now] = lambda: NOW.astimezone(ZoneInfo("Australia/Melbourne"))
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
