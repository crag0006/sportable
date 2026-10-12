"""Venues over the read model (data/sql/001 to 007).

- ``venue_card``            one row per venue with the four tiles flattened;
                            search reads this and nothing else
- ``venue_facility_detail`` one row per venue per tile with full provenance
                            (joined in ``_rows.assemble``)
- ``venue_access_chain``    the six links, venue page only
- ``amenity``               the corridor, computed per request (ADR-003)

Nothing here derives a status. Every status column was written once by the
pipeline; the only per-request computations are distances from the search
point and the corridor. Distances are on ``geography`` so the result is
metres, straight-line, the same basis as the builder's ``distance_m``.
"""

from typing import Any

from app.core.db import connection
from app.repositories._rows import SRID, VENUE_COLUMNS, assemble, to_date, to_datetime, to_float
from app.repositories.protocols import (
    CorridorFacilityRow,
    CorridorResult,
    ReferencePoint,
    VenueRow,
)

SQL_SEARCH = f"""
WITH ref AS (
    SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), {SRID})::geography AS g
)
SELECT {VENUE_COLUMNS},
       ST_Distance(c.geom::geography, ref.g) AS distance_m
  FROM venue_card c, ref
 WHERE ST_DWithin(c.geom::geography, ref.g, %(radius_m)s)
   AND EXISTS (SELECT 1 FROM unnest(c.sports) AS s(sport)
                WHERE lower(s.sport) = lower(%(sport)s))
 ORDER BY distance_m, c.venue_id
 LIMIT 1000
"""

SQL_VENUE = f"""
SELECT {VENUE_COLUMNS},
       NULL::double precision AS distance_m
  FROM venue_card c
 WHERE c.venue_id = %(id)s
"""

SQL_CORRIDOR = f"""
WITH path AS (
    SELECT ST_MakeLine(
               ST_SetSRID(ST_MakePoint(%(origin_lon)s, %(origin_lat)s), {SRID}),
               ST_SetSRID(ST_MakePoint(%(venue_lon)s, %(venue_lat)s), {SRID})
           ) AS line
)
SELECT a.kind::text AS kind, a.name, a.address,
       ST_Y(a.geom) AS lat, ST_X(a.geom) AS lon,
       a.opening_hours, a.key_required, a.retrieved_at,
       ST_Distance(a.geom::geography, p.line::geography) AS distance_from_path_m,
       ST_LineLocatePoint(p.line, a.geom) AS fraction,
       s.source_id, s.name AS source_name, s.publisher_last_updated AS source_updated,
       s.stale_after_days
  FROM amenity a
 CROSS JOIN path p
  LEFT JOIN source s ON s.source_id = a.source_id
 WHERE a.kind::text = ANY(%(kinds)s)
   AND ST_DWithin(a.geom::geography, p.line::geography, %(within_m)s)
 ORDER BY fraction, distance_from_path_m, a.amenity_id
 LIMIT 200
"""

SQL_AMENITY_TOTALS = """
SELECT kind::text AS kind, count(*) AS total
  FROM amenity
 WHERE kind::text = ANY(%(kinds)s)
 GROUP BY kind
"""


def _corridor_row(r: dict[str, Any]) -> CorridorFacilityRow:
    """One ``SQL_CORRIDOR`` row as a ``CorridorFacilityRow``."""
    return CorridorFacilityRow(
        kind=r["kind"],
        name=r["name"],
        address=r["address"],
        lat=float(r["lat"]),
        lon=float(r["lon"]),
        distance_from_path_m=to_float(r["distance_from_path_m"]) or 0.0,
        fraction=float(r["fraction"]),
        opening_hours=r["opening_hours"],
        key_required=r["key_required"],
        source_id=r["source_id"],
        source_name=r["source_name"],
        source_updated=to_date(r["source_updated"]),
        stale_after_days=r["stale_after_days"],
        retrieved_at=to_datetime(r["retrieved_at"]),
    )


class PostgresVenueRepository:
    """``VenueRepository`` over PostGIS."""

    def search(self, sport: str, reference: ReferencePoint, radius_m: int) -> list[VenueRow]:
        """Venues for the sport within ``radius_m`` of the point, nearest first."""
        params = {
            "sport": sport,
            "lat": reference.latitude,
            "lon": reference.longitude,
            "radius_m": radius_m,
        }
        with connection() as conn:
            rows = conn.execute(SQL_SEARCH, params).fetchall()
            return assemble(conn, rows, with_chain=False)

    def get_venue(self, venue_id: str) -> VenueRow | None:
        """One venue with tiles and access chain, or None when the id is unknown."""
        with connection() as conn:
            row = conn.execute(SQL_VENUE, {"id": venue_id}).fetchone()
            if row is None:
                return None
            venues = assemble(conn, [row], with_chain=True)
        return venues[0] if venues else None

    def corridor(
        self, origin: ReferencePoint, venue: VenueRow, within_m: int, kinds: list[str]
    ) -> CorridorResult:
        """Amenities of the kinds within ``within_m`` of the origin-to-venue line."""
        params = {
            "origin_lat": origin.latitude,
            "origin_lon": origin.longitude,
            "venue_lat": venue.latitude,
            "venue_lon": venue.longitude,
            "within_m": within_m,
            "kinds": kinds,
        }
        with connection() as conn:
            rows = conn.execute(SQL_CORRIDOR, params).fetchall()
            totals = {
                t["kind"]: t["total"]
                for t in conn.execute(SQL_AMENITY_TOTALS, {"kinds": kinds}).fetchall()
            }
        return CorridorResult(facilities=tuple(_corridor_row(r) for r in rows), totals=totals)
