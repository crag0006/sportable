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
    PlaceRow,
    ReferencePoint,
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
            _row("accessible_toilet", "not_available", "publisher_attribute", None, FACILITIES),
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


class FakeRepository:
    def list_sports(self) -> list[SportRow]:
        return [SportRow("Basketball", 3), SportRow("Netball", 1), SportRow("Swimming", 1)]

    def list_places(self) -> list[PlaceRow]:
        return [PlaceRow("Northcote", "3070", 1), PlaceRow("Preston", "3072", 1)]

    def resolve_reference(self, suburb: str | None, postcode: str | None) -> ReferencePoint | None:
        if (suburb or "").lower() == "preston" or postcode == "3072":
            return PRESTON
        return None

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
