"""An in-memory repository so the API can be tested without PostGIS.

The rows mirror what the loader and status builder write, including the two
edge cases the Data team called out: a facility confirmed at the venue itself
(no distance) and a nearest amenity beyond 1 km (distance kept, status
``no_published_information``).
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from app.api.deps import get_repository
from app.main import app
from app.repositories.protocols import (
    ChainRow,
    CorridorFacilityRow,
    CorridorResult,
    FacilityRow,
    LocationMatch,
    LocationSuggestion,
    PlaceRow,
    ReferencePoint,
    SourceRow,
    SportEntry,
    SportRow,
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


class FakeRepository:
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
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
