"""PostGIS-backed repository. Every query targets tables from data/sql/001-003.

Distances are computed on ``geography`` so the result is metres, matching how
the status builder computed ``venue_amenity_status.distance_m``. Both are
straight-line, not walking distance.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.db import connection
from app.repositories.protocols import (
    ChainRow,
    FacilityRow,
    PlaceRow,
    ReferencePoint,
    SportEntry,
    SportRow,
    VenueRow,
)

SRID = 7844

SQL_SPORTS = """
SELECT sport AS name, count(DISTINCT venue_id) AS venue_count
  FROM venue_sport
 GROUP BY sport
 ORDER BY sport
"""

SQL_PLACES = """
SELECT suburb_name AS suburb, postcode, count(*) AS venue_count
  FROM venue
 WHERE suburb_name IS NOT NULL AND postcode IS NOT NULL
 GROUP BY suburb_name, postcode
 ORDER BY suburb_name, postcode
"""

# The ABS suburb polygon's representative point. Largest polygon wins when a
# name is shared, which is rare inside Greater Melbourne.
SQL_SUBURB_POINT = """
SELECT ST_Y(p) AS lat, ST_X(p) AS lon
  FROM (SELECT ST_PointOnSurface(geom) AS p
          FROM suburb
         WHERE lower(suburb_name) = lower(%(name)s)
         ORDER BY ST_Area(geom) DESC
         LIMIT 1) s
"""

# Fallbacks when the typed suburb is not an ABS locality name (e.g. "Melbourne
# CBD"): the centre of the venues the facilities list files under that name /
# postcode. Still a truthful "measured from" point, just derived differently.
SQL_VENUE_CENTROID_BY_SUBURB = """
SELECT ST_Y(c) AS lat, ST_X(c) AS lon
  FROM (SELECT ST_Centroid(ST_Collect(geom)) AS c
          FROM venue
         WHERE lower(suburb_name) = lower(%(name)s)
           AND (%(postcode)s::text IS NULL OR postcode = %(postcode)s)) v
"""

SQL_VENUE_CENTROID_BY_POSTCODE = """
SELECT ST_Y(c) AS lat, ST_X(c) AS lon
  FROM (SELECT ST_Centroid(ST_Collect(geom)) AS c
          FROM venue
         WHERE postcode = %(postcode)s) v
"""

SQL_SEARCH = f"""
WITH ref AS (
    SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), {SRID})::geography AS g
)
SELECT v.venue_id, v.name, v.suburb_name, v.postcode, v.lga_name, v.full_address,
       v.retrieved_at,
       ST_Y(v.geom) AS lat, ST_X(v.geom) AS lon,
       ST_Distance(v.geom::geography, ref.g) AS distance_m
  FROM venue v, ref
 WHERE ST_DWithin(v.geom::geography, ref.g, %(radius_m)s)
   AND EXISTS (SELECT 1
                 FROM venue_sport vs
                WHERE vs.venue_id = v.venue_id
                  AND lower(vs.sport) = lower(%(sport)s))
 ORDER BY distance_m, v.venue_id
 LIMIT 1000
"""

SQL_VENUE = """
SELECT venue_id, name, suburb_name, postcode, lga_name, full_address, retrieved_at,
       ST_Y(geom) AS lat, ST_X(geom) AS lon,
       NULL::double precision AS distance_m
  FROM venue
 WHERE venue_id = %(id)s
"""

SQL_SPORTS_FOR = """
SELECT venue_id, sport, surface_type
  FROM venue_sport
 WHERE venue_id = ANY(%(ids)s)
 ORDER BY venue_id, sport
"""

SQL_STATUS_FOR = """
SELECT s.venue_id, s.kind::text AS kind, s.status::text AS status, s.basis::text AS basis,
       s.distance_m,
       a.name AS amenity_name, a.address AS amenity_address, a.opening_hours,
       ST_Y(a.geom) AS amenity_lat, ST_X(a.geom) AS amenity_lon,
       a.key_required, a.is_inside_venue, a.retrieved_at AS amenity_retrieved_at,
       sa.name AS amenity_source_name, sa.publisher_last_updated AS amenity_source_updated,
       sv.name AS venue_source_name, sv.publisher_last_updated AS venue_source_updated,
       v.retrieved_at AS venue_retrieved_at
  FROM venue_amenity_status s
  JOIN venue v ON v.venue_id = s.venue_id
  LEFT JOIN source sv ON sv.source_id = v.source_id
  LEFT JOIN amenity a ON a.amenity_id = s.nearest_amenity_id
  LEFT JOIN source sa ON sa.source_id = a.source_id
 WHERE s.venue_id = ANY(%(ids)s)
 ORDER BY s.venue_id, s.kind
"""

SQL_CHAIN = """
SELECT link::text AS link, status::text AS status, basis::text AS basis, detail
  FROM venue_access_chain
 WHERE venue_id = %(id)s
 ORDER BY link
"""


def _float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _facility(row: dict[str, Any]) -> FacilityRow:
    # A venue-level fact comes from the venue's own dataset (DS-01); a proximity
    # fact from the amenity's dataset. Attribute accordingly, never blend.
    if row["basis"] == "publisher_attribute":
        source_name = row["venue_source_name"]
        source_updated = row["venue_source_updated"]
        retrieved_at = row["venue_retrieved_at"]
    else:
        source_name = row["amenity_source_name"]
        source_updated = row["amenity_source_updated"]
        retrieved_at = row["amenity_retrieved_at"]
    return FacilityRow(
        kind=row["kind"],
        status=row["status"],
        basis=row["basis"],
        distance_m=_float(row["distance_m"]),
        amenity_name=row["amenity_name"],
        amenity_address=row["amenity_address"],
        amenity_lat=_float(row["amenity_lat"]),
        amenity_lon=_float(row["amenity_lon"]),
        opening_hours=row["opening_hours"],
        key_required=row["key_required"],
        is_inside_venue=row["is_inside_venue"],
        source_name=source_name,
        source_updated=source_updated if isinstance(source_updated, date) else None,
        retrieved_at=retrieved_at if isinstance(retrieved_at, datetime) else None,
    )


class PostgresVenueRepository:
    def list_sports(self) -> list[SportRow]:
        with connection() as conn:
            rows = conn.execute(SQL_SPORTS).fetchall()
        return [SportRow(name=r["name"], venue_count=int(r["venue_count"])) for r in rows]

    def list_places(self) -> list[PlaceRow]:
        with connection() as conn:
            rows = conn.execute(SQL_PLACES).fetchall()
        return [
            PlaceRow(suburb=r["suburb"], postcode=r["postcode"], venue_count=int(r["venue_count"]))
            for r in rows
        ]

    def resolve_reference(self, suburb: str | None, postcode: str | None) -> ReferencePoint | None:
        with connection() as conn:
            if suburb:
                label = f"the centre of {suburb}" + (f" {postcode}" if postcode else "")
                row = conn.execute(SQL_SUBURB_POINT, {"name": suburb}).fetchone()
                if row is None or row["lat"] is None:
                    row = conn.execute(
                        SQL_VENUE_CENTROID_BY_SUBURB, {"name": suburb, "postcode": postcode}
                    ).fetchone()
                if row is not None and row["lat"] is not None:
                    return ReferencePoint(label, float(row["lat"]), float(row["lon"]))
            if postcode:
                row = conn.execute(
                    SQL_VENUE_CENTROID_BY_POSTCODE, {"postcode": postcode}
                ).fetchone()
                if row is not None and row["lat"] is not None:
                    label = f"the centre of postcode {postcode}"
                    return ReferencePoint(label, float(row["lat"]), float(row["lon"]))
        return None

    def search(self, sport: str, reference: ReferencePoint, radius_m: int) -> list[VenueRow]:
        params = {
            "sport": sport,
            "lat": reference.latitude,
            "lon": reference.longitude,
            "radius_m": radius_m,
        }
        with connection() as conn:
            rows = conn.execute(SQL_SEARCH, params).fetchall()
            return self._assemble(conn, rows, with_chain=False)

    def get_venue(self, venue_id: str) -> VenueRow | None:
        with connection() as conn:
            row = conn.execute(SQL_VENUE, {"id": venue_id}).fetchone()
            if row is None:
                return None
            venues = self._assemble(conn, [row], with_chain=True)
        return venues[0] if venues else None

    def _assemble(self, conn: Any, rows: list[Any], with_chain: bool) -> list[VenueRow]:
        if not rows:
            return []
        ids = [r["venue_id"] for r in rows]

        sports: dict[str, list[SportEntry]] = defaultdict(list)
        for s in conn.execute(SQL_SPORTS_FOR, {"ids": ids}).fetchall():
            sports[s["venue_id"]].append(SportEntry(s["sport"], s["surface_type"]))

        facilities: dict[str, list[FacilityRow]] = defaultdict(list)
        for f in conn.execute(SQL_STATUS_FOR, {"ids": ids}).fetchall():
            facilities[f["venue_id"]].append(_facility(f))

        chain: dict[str, list[ChainRow]] = defaultdict(list)
        if with_chain:
            for vid in ids:
                for c in conn.execute(SQL_CHAIN, {"id": vid}).fetchall():
                    chain[vid].append(ChainRow(c["link"], c["status"], c["basis"], c["detail"]))

        return [
            VenueRow(
                venue_id=r["venue_id"],
                name=r["name"],
                suburb=r["suburb_name"],
                postcode=r["postcode"],
                lga=r["lga_name"],
                address=r["full_address"],
                latitude=float(r["lat"]),
                longitude=float(r["lon"]),
                distance_m=_float(r["distance_m"]),
                sports=tuple(sports[r["venue_id"]]),
                facilities=tuple(facilities[r["venue_id"]]),
                chain=tuple(chain[r["venue_id"]]),
                retrieved_at=r["retrieved_at"],
            )
            for r in rows
        ]
