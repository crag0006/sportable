"""Reference data over the read model: sports, places, the gazetteer, sources.

- ``sport_vocabulary``        the sport list (AC1.1.1: only sports with venues)
- ``program_sport_vocabulary`` publisher sport terms resolved to that list
                               through the reviewed crosswalk (data/sql/012),
                               so the event count beside a sport is right
- ``search_location``         typed suburb or postcode to a named point (AC1.1.3)
- ``source`` + ``load_run``   the register behind the Sources and licences page
"""

from typing import Any

from app.core.db import connection
from app.repositories._rows import to_date, to_datetime
from app.repositories.protocols import (
    LocationMatch,
    LocationSuggestion,
    PlaceRow,
    ReferencePoint,
    SourceRow,
    SportRow,
)

# ABS labels duplicate locality names with a state suffix ("Preston (Vic.)",
# "Melton (Melton - Vic.)"). People type "Preston"; match and display on the
# plain name and keep the code for identity.
PLAIN_LABEL = r"regexp_replace(label, '\s*\([^)]*\)$', '')"

# AC1.1.1 says the list holds sports that exist in loaded venues. Two changes
# to how that is read, both from the crosswalk:
#
#   1. The event count is counted through vocab_sport, not by comparing the
#      publisher's label to the venue name. Seventeen terms are spelled
#      differently on the two sides (Aqua aerobics is Swimming, Ultimate
#      (frisbee) is Flying Disk) and every one of them counted zero before.
#   2. A sport the crosswalk ADDS is offered too, with venue_count 0, when
#      programmes exist for it. Boccia, Goalball and Adaptive climbing are real
#      sports that no DS-01 venue records, and they are the ones this project's
#      users are most likely to look for. A sport with neither a venue nor a
#      programme is still not offered.
SQL_SPORTS = """
WITH event_counts AS (
    SELECT psv.vocab_sport AS sport,
           count(DISTINCT psv.program_id) AS event_count
      FROM program_sport_vocabulary psv
      JOIN program p ON p.program_id = psv.program_id
     WHERE psv.vocab_sport IS NOT NULL
       AND (p.kind = 'program' OR p.starts_at > now())
     GROUP BY 1
),
offered AS (
    SELECT sv.sport AS name, sv.venue_count
      FROM sport_vocabulary sv
     UNION ALL
    SELECT e.sport, 0
      FROM event_counts e
     WHERE NOT EXISTS (SELECT 1 FROM sport_vocabulary sv
                        WHERE lower(sv.sport) = lower(e.sport))
)
SELECT o.name, o.venue_count,
       coalesce(e.event_count, 0) AS event_count
  FROM offered o
  LEFT JOIN event_counts e ON lower(e.sport) = lower(o.name)
 WHERE %(q)s::text IS NULL
    OR lower(o.name) LIKE '%%' || lower(%(q)s) || '%%'
    OR similarity(lower(o.name), lower(%(q)s)) > 0.3
 ORDER BY o.name
"""

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

SQL_SOURCES = """
SELECT s.source_id, s.name, s.publisher, s.licence_name, s.licence_url,
       s.attribution_text, s.landing_page, s.publisher_scope, s.publisher_last_updated,
       s.stale_after_days,
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


def _reference(row: dict[str, Any]) -> ReferencePoint:
    """A gazetteer row as a named reference point (AC1.1.3)."""
    kind = "postcode" if row["location_kind"] == "postcode" else "suburb"
    label = (
        f"the centre of postcode {row['code']}"
        if kind == "postcode"
        else f"the centre of {row['label']}"
    )
    return ReferencePoint(label, float(row["lat"]), float(row["lon"]), kind=kind, code=row["code"])


def _source_row(r: dict[str, Any]) -> SourceRow:
    """One ``SQL_SOURCES`` row as a ``SourceRow``."""
    return SourceRow(
        source_id=r["source_id"],
        name=r["name"],
        publisher=r["publisher"],
        licence_name=r["licence_name"],
        licence_url=r["licence_url"],
        attribution_text=r["attribution_text"],
        landing_page=r["landing_page"],
        publisher_scope=r["publisher_scope"],
        publisher_last_updated=to_date(r["publisher_last_updated"]),
        stale_after_days=r["stale_after_days"],
        retrieved_at=to_datetime(r["retrieved_at"]),
        rows_loaded=r["rows_loaded"],
        outcome=r["outcome"],
    )


def _centroid_row(conn: Any, postcode: str) -> list[dict[str, Any]]:
    """The venue-centroid fallback for a postcode the gazetteer lacks."""
    centre = conn.execute(SQL_VENUE_CENTROID_BY_POSTCODE, {"postcode": postcode}).fetchone()
    if centre is None or centre["lat"] is None:
        return []
    return [
        {
            "location_kind": "postcode",
            "code": postcode,
            "label": postcode,
            "lat": centre["lat"],
            "lon": centre["lon"],
            "in_scope": True,
        }
    ]


def _candidate_rows(conn: Any, suburb: str | None, postcode: str | None) -> list[Any]:
    """Gazetteer rows for the typed place, trying the narrowest query first."""
    rows: list[Any] = []
    if suburb and postcode:
        params = {"name": suburb, "postcode": postcode}
        rows = conn.execute(SQL_LOCATION_BY_NAME_AND_POSTCODE, params).fetchall()
    if suburb and not rows:
        rows = conn.execute(SQL_LOCATION_BY_NAME, {"name": suburb}).fetchall()
    if not suburb and postcode:
        rows = conn.execute(SQL_LOCATION_BY_POSTCODE, {"postcode": postcode}).fetchall()
        if not rows:
            rows = _centroid_row(conn, postcode)
    return rows


def _with_postcode(reference: ReferencePoint, label: str, postcode: str) -> ReferencePoint:
    """Relabel a suburb point with the postcode the person typed."""
    return ReferencePoint(
        f"the centre of {label} {postcode}",
        reference.latitude,
        reference.longitude,
        kind="suburb",
        code=reference.code,
    )


class PostgresReferenceRepository:
    """``ReferenceRepository`` over PostGIS."""

    def list_sports(self, q: str | None = None) -> list[SportRow]:
        """Sports with venues or programmes, filtered by ``q`` when given."""
        with connection() as conn:
            rows = conn.execute(SQL_SPORTS, {"q": q or None}).fetchall()
        return [
            SportRow(
                name=r["name"],
                venue_count=int(r["venue_count"]),
                event_count=int(r["event_count"] or 0),
            )
            for r in rows
        ]

    def list_places(self) -> list[PlaceRow]:
        """Suburb and postcode pairs with their venue counts."""
        with connection() as conn:
            rows = conn.execute(SQL_PLACES).fetchall()
        return [
            PlaceRow(suburb=r["suburb"], postcode=r["postcode"], venue_count=int(r["venue_count"]))
            for r in rows
        ]

    def resolve_location(self, suburb: str | None, postcode: str | None) -> LocationMatch:
        """v0.2 §3.4: resolved, outside_coverage, or unresolved with suggestions."""
        typed = " ".join(p for p in (suburb, postcode) if p)
        with connection() as conn:
            rows = _candidate_rows(conn, suburb, postcode)
            in_scope = [r for r in rows if r["in_scope"]]
            if rows and not (len(in_scope) > 1 and not postcode):
                return self._match(in_scope[0] if in_scope else rows[0], suburb, postcode)
            # No row, or two in-scope suburbs share the name (Victoria-wide
            # scope): ask rather than guess the biggest polygon.
            suggestions = self._suggest(conn, suburb or typed, 5)
        return LocationMatch("unresolved", suggestions=suggestions)

    def _match(self, chosen: Any, suburb: str | None, postcode: str | None) -> LocationMatch:
        """The resolved or outside_coverage outcome for the chosen gazetteer row."""
        reference = _reference(chosen)
        if not chosen["in_scope"]:
            return LocationMatch(
                "outside_coverage",
                reference=None,
                matched_label=chosen["label"],
                matched_kind=reference.kind,
            )
        if suburb and postcode and reference.kind == "suburb":
            reference = _with_postcode(reference, chosen["label"], postcode)
        return LocationMatch(
            "resolved",
            reference=reference,
            matched_label=chosen["label"],
            matched_kind=reference.kind,
        )

    def _suggest(self, conn: Any, q: str, n: int) -> tuple[LocationSuggestion, ...]:
        """Up to ``n`` similar place names, labelled the way the dropdown shows them."""
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
        """The register rows with each source's latest completed load run."""
        with connection() as conn:
            rows = conn.execute(SQL_SOURCES).fetchall()
        return [_source_row(r) for r in rows]
