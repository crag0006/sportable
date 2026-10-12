"""Row conversion and venue assembly shared by the Postgres repositories.

The venue repository reads venues for search and the venue page; the event
repository reads the same venue rows to put the venue's own four tiles beside
each event (AC4.2.2). Both assemble a ``VenueRow`` the same way, from the same
SQL, so that code lives once here and neither repository imports the other.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.repositories.protocols import ChainRow, FacilityRow, SportEntry, VenueRow

SRID = 7844

VENUE_COLUMNS = """
       c.venue_id, c.name, c.suburb_name, c.postcode, c.lga_code, c.lga_name,
       c.full_address, c.retrieved_at, c.ownership, c.purpose, c.changeroom_description,
       c.sports, c.surface_types,
       ST_Y(c.geom) AS lat, ST_X(c.geom) AS lon
"""

SQL_VENUES_BY_ID = f"""
SELECT {VENUE_COLUMNS},
       NULL::double precision AS distance_m
  FROM venue_card c
 WHERE c.venue_id = ANY(%(ids)s)
"""

# The four tiles with full provenance. The view already carries the status
# source; the amenity's own source is joined for the "nearest recorded but
# beyond 1 km" rows, where the builder wrote no status source (nothing was
# confirmed) but the distance still has a publisher.
SQL_FACILITIES_FOR = """
SELECT d.venue_id, d.kind, d.status, d.basis, d.distance_m,
       d.within_250m, d.within_500m, d.within_1000m,
       coalesce(d.source_id, a.source_id)            AS source_id,
       coalesce(d.source_name, asrc.name)            AS source_name,
       coalesce(d.source_last_updated, asrc.publisher_last_updated) AS source_updated,
       coalesce(a.retrieved_at, v.retrieved_at)      AS retrieved_at,
       d.amenity_id, d.amenity_name, d.amenity_address,
       ST_Y(a.geom) AS amenity_lat, ST_X(a.geom) AS amenity_lon,
       a.is_inside_venue,
       d.location_relative_to_venue,
       d.opening_hours, d.key_required, d.mlak_24h, d.payment_required, d.access_note,
       d.changing_places, d.has_shower, d.ambulant, d.left_hand_transfer, d.right_hand_transfer,
       d.opening_hours_unrecorded, d.key_requirement_unrecorded, d.transport_mode,
       d.detail_amenity_id, d.detail_source_id, d.detail_source_name,
       d.detail_source_last_updated, d.detail_distance_m,
       dsrc.stale_after_days AS detail_stale_after_days,
       d.alternative_amenity_id, d.alternative_name, d.alternative_distance_m,
       ST_Y(alt.geom) AS alternative_lat, ST_X(alt.geom) AS alternative_lon,
       d.alternative_opening_hours, d.alternative_key_required,
       alt.source_id AS alternative_source_id, d.alternative_source_name,
       d.alternative_source_last_updated,
       altsrc.stale_after_days AS alternative_stale_after_days
  FROM venue_facility_detail d
  JOIN venue v      ON v.venue_id = d.venue_id
  LEFT JOIN amenity a    ON a.amenity_id = d.amenity_id
  LEFT JOIN source  asrc ON asrc.source_id = a.source_id
  LEFT JOIN source  dsrc ON dsrc.source_id = d.detail_source_id
  LEFT JOIN amenity alt  ON alt.amenity_id = d.alternative_amenity_id
  LEFT JOIN source  altsrc ON altsrc.source_id = alt.source_id
 WHERE d.venue_id = ANY(%(ids)s)
 ORDER BY d.venue_id, d.kind
"""

SQL_CHAIN = """
SELECT link::text AS link, status::text AS status, basis::text AS basis, detail
  FROM venue_access_chain
 WHERE venue_id = %(id)s
 ORDER BY link
"""


def to_float(value: Any) -> float | None:
    """A numeric column (possibly ``Decimal``) as a float, or None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def to_date(value: Any) -> date | None:
    """A date column as a date, or None for anything else."""
    return value if isinstance(value, date) else None


def to_datetime(value: Any) -> datetime | None:
    """A timestamp column as a datetime, or None for anything else."""
    return value if isinstance(value, datetime) else None


def _detail_columns(row: dict[str, Any]) -> dict[str, Any]:
    """The ``venue_facility_detail`` description columns (data/sql/005)."""
    return {
        "within_250m": row["within_250m"],
        "within_500m": row["within_500m"],
        "within_1000m": row["within_1000m"],
        "location_relative_to_venue": row["location_relative_to_venue"],
        "opening_hours_unrecorded": row["opening_hours_unrecorded"],
        "key_requirement_unrecorded": row["key_requirement_unrecorded"],
        "mlak_24h": row["mlak_24h"],
        "payment_required": row["payment_required"],
        "access_note": row["access_note"],
        "changing_places": row["changing_places"],
        "has_shower": row["has_shower"],
        "ambulant": row["ambulant"],
        "left_hand_transfer": row["left_hand_transfer"],
        "right_hand_transfer": row["right_hand_transfer"],
        "transport_mode": row["transport_mode"],
    }


def _attachment_columns(row: dict[str, Any]) -> dict[str, Any]:
    """The attached description and the nearby alternative (data/sql/007)."""
    return {
        "detail_amenity_id": row["detail_amenity_id"],
        "detail_source_id": row["detail_source_id"],
        "detail_source_name": row["detail_source_name"],
        "detail_source_updated": to_date(row["detail_source_last_updated"]),
        "detail_stale_after_days": row["detail_stale_after_days"],
        "detail_distance_m": to_float(row["detail_distance_m"]),
        "alternative_amenity_id": row["alternative_amenity_id"],
        "alternative_name": row["alternative_name"],
        "alternative_distance_m": to_float(row["alternative_distance_m"]),
        "alternative_lat": to_float(row["alternative_lat"]),
        "alternative_lon": to_float(row["alternative_lon"]),
        "alternative_opening_hours": row["alternative_opening_hours"],
        "alternative_key_required": row["alternative_key_required"],
        "alternative_source_id": row["alternative_source_id"],
        "alternative_source_name": row["alternative_source_name"],
        "alternative_source_updated": to_date(row["alternative_source_last_updated"]),
        "alternative_stale_after_days": row["alternative_stale_after_days"],
    }


def facility_row(row: dict[str, Any]) -> FacilityRow:
    """One ``SQL_FACILITIES_FOR`` row as a ``FacilityRow``. Types only, no rules."""
    return FacilityRow(
        kind=row["kind"],
        status=row["status"],
        basis=row["basis"],
        distance_m=to_float(row["distance_m"]),
        amenity_name=row["amenity_name"],
        amenity_address=row["amenity_address"],
        amenity_lat=to_float(row["amenity_lat"]),
        amenity_lon=to_float(row["amenity_lon"]),
        opening_hours=row["opening_hours"],
        key_required=row["key_required"],
        is_inside_venue=row["is_inside_venue"],
        source_name=row["source_name"],
        source_updated=to_date(row["source_updated"]),
        retrieved_at=to_datetime(row["retrieved_at"]),
        source_id=row["source_id"],
        **_detail_columns(row),
        **_attachment_columns(row),
    )


def _venue_row(r: dict[str, Any], facilities: list[FacilityRow], chain: list[ChainRow]) -> VenueRow:
    """One ``venue_card`` row plus its tiles and chain as a ``VenueRow``."""
    return VenueRow(
        venue_id=r["venue_id"],
        name=r["name"],
        suburb=r["suburb_name"],
        postcode=r["postcode"],
        lga=r["lga_name"],
        address=r["full_address"],
        latitude=float(r["lat"]),
        longitude=float(r["lon"]),
        distance_m=to_float(r["distance_m"]),
        sports=tuple(SportEntry(s, None) for s in (r["sports"] or [])),
        facilities=tuple(facilities),
        chain=tuple(chain),
        retrieved_at=r["retrieved_at"],
        surface_types=tuple(r["surface_types"] or []),
        ownership=r["ownership"],
        purpose=r["purpose"],
        changeroom_description=r["changeroom_description"],
        lga_code=r["lga_code"],
    )


def assemble(conn: Any, rows: list[Any], with_chain: bool) -> list[VenueRow]:
    """Attach the four tiles (and, for the venue page, the chain) to venue rows."""
    if not rows:
        return []
    ids = [r["venue_id"] for r in rows]
    facilities: dict[str, list[FacilityRow]] = defaultdict(list)
    for f in conn.execute(SQL_FACILITIES_FOR, {"ids": ids}).fetchall():
        facilities[f["venue_id"]].append(facility_row(f))
    chain: dict[str, list[ChainRow]] = defaultdict(list)
    if with_chain:
        for vid in ids:
            for c in conn.execute(SQL_CHAIN, {"id": vid}).fetchall():
                chain[vid].append(ChainRow(c["link"], c["status"], c["basis"], c["detail"]))
    return [_venue_row(r, facilities[r["venue_id"]], chain[r["venue_id"]]) for r in rows]


def venues_by_id(conn: Any, ids: list[str]) -> dict[str, VenueRow]:
    """Venue rows (tiles, no chain) keyed by id, for the events beside them."""
    unique = sorted(set(ids))
    if not unique:
        return {}
    rows = conn.execute(SQL_VENUES_BY_ID, {"ids": unique}).fetchall()
    return {v.venue_id: v for v in assemble(conn, rows, with_chain=False)}
