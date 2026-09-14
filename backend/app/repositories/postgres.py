"""PostGIS-backed repository over the read model (data/sql/001 to 007).

What is read from where, and why:

- ``sport_vocabulary``     the sport list (AC1.1.1: only sports with venues)
- ``search_location``      typed suburb or postcode to a named point (AC1.1.3)
- ``venue_card``           one row per venue with the four tiles flattened;
                           search reads this and nothing else
- ``venue_facility_detail`` one row per venue per tile with full provenance,
                           the attached description and the nearby alternative
- ``venue_access_chain``   the six links
- ``source`` + ``load_run`` the register behind the Sources and licences page
- ``amenity``              the corridor, computed per request (ADR-003)

Nothing here derives a status. Every status column was written once by the
pipeline; the only per-request computations are distances from the search
point and the corridor. Distances are on ``geography`` so the result is
metres, straight-line, the same basis as the builder's ``distance_m``.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.db import connection
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

SRID = 7844

# ABS labels duplicate locality names with a state suffix ("Preston (Vic.)",
# "Melton (Melton - Vic.)"). People type "Preston"; match and display on the
# plain name and keep the code for identity.
PLAIN_LABEL = r"regexp_replace(label, '\s*\([^)]*\)$', '')"

# ------------------------------------------------------------------ sports
SQL_SPORTS = """
SELECT sport AS name, venue_count
  FROM sport_vocabulary
 WHERE %(q)s::text IS NULL
    OR lower(sport) LIKE '%%' || lower(%(q)s) || '%%'
    OR similarity(lower(sport), lower(%(q)s)) > 0.3
 ORDER BY sport
"""

# ------------------------------------------------------------------ places
# The dropdown feed. Venues carry a publisher postcode, the gazetteer does not
# always (DS-08 is loaded separately), so the pairs come from the venue table.
SQL_PLACES = """
SELECT suburb_name AS suburb, postcode, count(*) AS venue_count
  FROM venue
 WHERE suburb_name IS NOT NULL AND postcode IS NOT NULL
 GROUP BY suburb_name, postcode
 ORDER BY suburb_name, postcode
"""

# A typed suburb name. ``in_greater_melbourne`` is the gazetteer's in-scope
# flag (the column kept its Iteration 1 name when scope widened to Victoria).
SQL_LOCATION_BY_NAME = f"""
SELECT location_kind, code, {PLAIN_LABEL} AS label, display_name,
       ST_Y(search_point) AS lat, ST_X(search_point) AS lon,
       in_greater_melbourne AS in_scope
  FROM search_location
 WHERE location_kind = 'suburb'
   AND lower({PLAIN_LABEL}) = lower(%(name)s)
 ORDER BY in_scope DESC, ST_Area(geom) DESC
"""

# The same, narrowed by a postcode when the postal-area layer is loaded: the
# suburb whose representative point falls inside that postal area.
SQL_LOCATION_BY_NAME_AND_POSTCODE = f"""
SELECT s.location_kind, s.code, {PLAIN_LABEL.replace("label", "s.label")} AS label,
       s.display_name,
       ST_Y(s.search_point) AS lat, ST_X(s.search_point) AS lon,
       s.in_greater_melbourne AS in_scope
  FROM search_location s
  JOIN search_location p
    ON p.location_kind = 'postcode' AND p.code = %(postcode)s
   AND ST_Intersects(p.geom, s.search_point)
 WHERE s.location_kind = 'suburb'
   AND lower({PLAIN_LABEL.replace("label", "s.label")}) = lower(%(name)s)
 ORDER BY s.in_greater_melbourne DESC
"""

SQL_LOCATION_BY_POSTCODE = """
SELECT location_kind, code, label, display_name,
       ST_Y(search_point) AS lat, ST_X(search_point) AS lon,
       in_greater_melbourne AS in_scope
  FROM search_location
 WHERE location_kind = 'postcode' AND code = %(postcode)s
"""

# Fallback for a postcode before DS-08 is loaded: the centre of the venues the
# facilities list files under it. Still a truthful "measured from" point.
SQL_VENUE_CENTROID_BY_POSTCODE = """
SELECT ST_Y(c) AS lat, ST_X(c) AS lon
  FROM (SELECT ST_Centroid(ST_Collect(geom)) AS c
          FROM venue
         WHERE postcode = %(postcode)s) v
"""

# AC1.1.4: a typo gets suggestions, never an empty list. The postcode shown
# beside a suburb is the one most of its venues carry.
SQL_LOCATION_SUGGEST = f"""
WITH g AS (
    SELECT {PLAIN_LABEL} AS label, location_kind, code, in_greater_melbourne
      FROM search_location
)
SELECT g.label, g.location_kind, g.code,
       (SELECT v.postcode FROM venue v
         WHERE lower(v.suburb_name) = lower(g.label) AND v.postcode IS NOT NULL
         GROUP BY v.postcode ORDER BY count(*) DESC LIMIT 1) AS postcode
  FROM g
 WHERE similarity(lower(g.label), lower(%(q)s)) > 0.25
 ORDER BY similarity(lower(g.label), lower(%(q)s)) DESC, g.in_greater_melbourne DESC, g.label
 LIMIT %(n)s
"""

# ------------------------------------------------------------------ venues
VENUE_COLUMNS = """
       c.venue_id, c.name, c.suburb_name, c.postcode, c.lga_code, c.lga_name,
       c.full_address, c.retrieved_at, c.ownership, c.purpose, c.changeroom_description,
       c.sports, c.surface_types,
       ST_Y(c.geom) AS lat, ST_X(c.geom) AS lon
"""

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
       d.alternative_amenity_id, d.alternative_name, d.alternative_distance_m,
       ST_Y(alt.geom) AS alternative_lat, ST_X(alt.geom) AS alternative_lon,
       d.alternative_opening_hours, d.alternative_key_required,
       alt.source_id AS alternative_source_id, d.alternative_source_name,
       d.alternative_source_last_updated
  FROM venue_facility_detail d
  JOIN venue v      ON v.venue_id = d.venue_id
  LEFT JOIN amenity a    ON a.amenity_id = d.amenity_id
  LEFT JOIN source  asrc ON asrc.source_id = a.source_id
  LEFT JOIN amenity alt  ON alt.amenity_id = d.alternative_amenity_id
 WHERE d.venue_id = ANY(%(ids)s)
 ORDER BY d.venue_id, d.kind
"""

SQL_CHAIN = """
SELECT link::text AS link, status::text AS status, basis::text AS basis, detail
  FROM venue_access_chain
 WHERE venue_id = %(id)s
 ORDER BY link
"""

# ------------------------------------------------------------------ sources
SQL_SOURCES = """
SELECT s.source_id, s.name, s.publisher, s.licence_name, s.licence_url,
       s.attribution_text, s.landing_page, s.publisher_scope, s.publisher_last_updated,
       r.completed_at AS retrieved_at, r.rows_loaded, r.outcome
  FROM source s
  LEFT JOIN LATERAL (
      SELECT completed_at, rows_loaded, outcome
        FROM load_run
       WHERE source_id = s.source_id AND completed_at IS NOT NULL
       ORDER BY completed_at DESC
       LIMIT 1
  ) r ON true
 ORDER BY s.source_id
"""

# ------------------------------------------------------------------ corridor
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
       s.name AS source_name, s.publisher_last_updated AS source_updated
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


def _float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _date(value: Any) -> date | None:
    return value if isinstance(value, date) else None


def _datetime(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _facility(row: dict[str, Any]) -> FacilityRow:
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
        source_name=row["source_name"],
        source_updated=_date(row["source_updated"]),
        retrieved_at=_datetime(row["retrieved_at"]),
        source_id=row["source_id"],
        within_250m=row["within_250m"],
        within_500m=row["within_500m"],
        within_1000m=row["within_1000m"],
        location_relative_to_venue=row["location_relative_to_venue"],
        opening_hours_unrecorded=row["opening_hours_unrecorded"],
        key_requirement_unrecorded=row["key_requirement_unrecorded"],
        mlak_24h=row["mlak_24h"],
        payment_required=row["payment_required"],
        access_note=row["access_note"],
        changing_places=row["changing_places"],
        has_shower=row["has_shower"],
        ambulant=row["ambulant"],
        left_hand_transfer=row["left_hand_transfer"],
        right_hand_transfer=row["right_hand_transfer"],
        transport_mode=row["transport_mode"],
        detail_amenity_id=row["detail_amenity_id"],
        detail_source_id=row["detail_source_id"],
        detail_source_name=row["detail_source_name"],
        detail_source_updated=_date(row["detail_source_last_updated"]),
        detail_distance_m=_float(row["detail_distance_m"]),
        alternative_amenity_id=row["alternative_amenity_id"],
        alternative_name=row["alternative_name"],
        alternative_distance_m=_float(row["alternative_distance_m"]),
        alternative_lat=_float(row["alternative_lat"]),
        alternative_lon=_float(row["alternative_lon"]),
        alternative_opening_hours=row["alternative_opening_hours"],
        alternative_key_required=row["alternative_key_required"],
        alternative_source_id=row["alternative_source_id"],
        alternative_source_name=row["alternative_source_name"],
        alternative_source_updated=_date(row["alternative_source_last_updated"]),
    )


def _reference(row: dict[str, Any]) -> ReferencePoint:
    kind = "postcode" if row["location_kind"] == "postcode" else "suburb"
    label = (
        f"the centre of postcode {row['code']}"
        if kind == "postcode"
        else f"the centre of {row['label']}"
    )
    return ReferencePoint(label, float(row["lat"]), float(row["lon"]), kind=kind, code=row["code"])


class PostgresVenueRepository:
    # ------------------------------------------------------------ reference
    def list_sports(self, q: str | None = None) -> list[SportRow]:
        with connection() as conn:
            rows = conn.execute(SQL_SPORTS, {"q": q or None}).fetchall()
        return [SportRow(name=r["name"], venue_count=int(r["venue_count"])) for r in rows]

    def list_places(self) -> list[PlaceRow]:
        with connection() as conn:
            rows = conn.execute(SQL_PLACES).fetchall()
        return [
            PlaceRow(suburb=r["suburb"], postcode=r["postcode"], venue_count=int(r["venue_count"]))
            for r in rows
        ]

    def resolve_reference(self, suburb: str | None, postcode: str | None) -> ReferencePoint | None:
        """v0.1 entry point: a point or nothing. Kept for search and ``?from=``."""
        return self.resolve_location(suburb, postcode).reference

    def resolve_location(self, suburb: str | None, postcode: str | None) -> LocationMatch:
        """v0.2 §3.4: resolved, outside_coverage, or unresolved with suggestions."""
        typed = " ".join(p for p in (suburb, postcode) if p)
        with connection() as conn:
            rows: list[Any] = []
            if suburb and postcode:
                rows = conn.execute(
                    SQL_LOCATION_BY_NAME_AND_POSTCODE, {"name": suburb, "postcode": postcode}
                ).fetchall()
            if suburb and not rows:
                rows = conn.execute(SQL_LOCATION_BY_NAME, {"name": suburb}).fetchall()
            if not suburb and postcode:
                rows = conn.execute(SQL_LOCATION_BY_POSTCODE, {"postcode": postcode}).fetchall()
                if not rows:
                    centre = conn.execute(
                        SQL_VENUE_CENTROID_BY_POSTCODE, {"postcode": postcode}
                    ).fetchone()
                    if centre is not None and centre["lat"] is not None:
                        rows = [
                            {
                                "location_kind": "postcode",
                                "code": postcode,
                                "label": postcode,
                                "lat": centre["lat"],
                                "lon": centre["lon"],
                                "in_scope": True,
                            }
                        ]

            if rows:
                in_scope = [r for r in rows if r["in_scope"]]
                if len(in_scope) > 1 and not postcode:
                    # Two in-scope suburbs share the name (Victoria-wide scope):
                    # ask rather than guess the biggest polygon.
                    suggestions = self._suggest(conn, suburb or typed, 5)
                    return LocationMatch("unresolved", suggestions=suggestions)
                chosen = in_scope[0] if in_scope else rows[0]
                reference = _reference(chosen)
                if not chosen["in_scope"]:
                    return LocationMatch(
                        "outside_coverage",
                        reference=None,
                        matched_label=chosen["label"],
                        matched_kind=reference.kind,
                    )
                if suburb and postcode and reference.kind == "suburb":
                    reference = ReferencePoint(
                        f"the centre of {chosen['label']} {postcode}",
                        reference.latitude,
                        reference.longitude,
                        kind="suburb",
                        code=reference.code,
                    )
                return LocationMatch(
                    "resolved",
                    reference=reference,
                    matched_label=chosen["label"],
                    matched_kind=reference.kind,
                )

            suggestions = self._suggest(conn, suburb or typed, 5)
        return LocationMatch("unresolved", suggestions=suggestions)

    def _suggest(self, conn: Any, q: str, n: int) -> tuple[LocationSuggestion, ...]:
        rows = conn.execute(SQL_LOCATION_SUGGEST, {"q": q, "n": n}).fetchall()
        out: list[LocationSuggestion] = []
        for r in rows:
            label = r["label"]
            if r["location_kind"] == "suburb" and r["postcode"]:
                label = f"{label} {r['postcode']}"
            elif r["location_kind"] == "postcode":
                label = f"postcode {r['code']}"
            out.append(LocationSuggestion(label=label, kind=r["location_kind"], code=r["code"]))
        return tuple(out)

    def list_sources(self) -> list[SourceRow]:
        with connection() as conn:
            rows = conn.execute(SQL_SOURCES).fetchall()
        return [
            SourceRow(
                source_id=r["source_id"],
                name=r["name"],
                publisher=r["publisher"],
                licence_name=r["licence_name"],
                licence_url=r["licence_url"],
                attribution_text=r["attribution_text"],
                landing_page=r["landing_page"],
                publisher_scope=r["publisher_scope"],
                publisher_last_updated=_date(r["publisher_last_updated"]),
                retrieved_at=_datetime(r["retrieved_at"]),
                rows_loaded=r["rows_loaded"],
                outcome=r["outcome"],
            )
            for r in rows
        ]

    # --------------------------------------------------------------- venues
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

    def corridor(
        self, origin: ReferencePoint, venue: VenueRow, within_m: int, kinds: list[str]
    ) -> CorridorResult:
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
        facilities = tuple(
            CorridorFacilityRow(
                kind=r["kind"],
                name=r["name"],
                address=r["address"],
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                distance_from_path_m=_float(r["distance_from_path_m"]) or 0.0,
                fraction=float(r["fraction"]),
                opening_hours=r["opening_hours"],
                key_required=r["key_required"],
                source_name=r["source_name"],
                source_updated=_date(r["source_updated"]),
                retrieved_at=_datetime(r["retrieved_at"]),
            )
            for r in rows
        )
        return CorridorResult(facilities=facilities, totals=totals)

    def _assemble(self, conn: Any, rows: list[Any], with_chain: bool) -> list[VenueRow]:
        if not rows:
            return []
        ids = [r["venue_id"] for r in rows]

        facilities: dict[str, list[FacilityRow]] = defaultdict(list)
        for f in conn.execute(SQL_FACILITIES_FOR, {"ids": ids}).fetchall():
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
                sports=tuple(SportEntry(s, None) for s in (r["sports"] or [])),
                facilities=tuple(facilities[r["venue_id"]]),
                chain=tuple(chain[r["venue_id"]]),
                retrieved_at=r["retrieved_at"],
                surface_types=tuple(r["surface_types"] or []),
                ownership=r["ownership"],
                purpose=r["purpose"],
                changeroom_description=r["changeroom_description"],
                lga_code=r["lga_code"],
            )
            for r in rows
        ]
