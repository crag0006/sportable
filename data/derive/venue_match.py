"""Match events to DS-01 venues (data/sql/008, API contract v0.2 section 7).

Runs after every event load, in the derive stage, like status_builder. It
fills ``event.venue_id`` and records how the decision was made, so a matched
event shows its venue's four access tiles and an unmatched one shows "no
published information" for all four.

THE RULE, AND WHY DISTANCE ALONE IS NOT ENOUGH

Against the 552 AAA Play facilities, the nearest DS-01 venue within 20 m was a
different place twice: a cafe 5 m from a gym, and netball courts 16 m from a
leisure centre they sit inside but are not. Both are honest neighbours and
wrong answers. So a match needs the name to agree as well:

    name_and_distance  within 150 m AND trigram similarity > 0.3  (the normal case)
    distance_only      within 25 m           (same point, names differ: "SportLink" vs
                                              "Sportlink Vermont South")
    name_only          similarity >= 0.6 AND within 400 m  (same name, pin on the car park)
    none               everything else; the event is still listed

Thresholds are recorded on the row (``venue_match_basis``) so they can be
audited and changed without a reload. Run with ``--report`` to print the
distribution the way the source assessment did.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

NAME_AND_DISTANCE_M = 150
DISTANCE_ONLY_M = 25
NAME_ONLY_M = 400
MIN_SIMILARITY = 0.3
STRONG_SIMILARITY = 0.6

# The nearest venue by straight-line distance, with the name similarity of
# that one candidate. One candidate is deliberate: the second-nearest venue
# with a better name is usually a different place with a similar name.
SQL_CANDIDATES = """
SELECT e.event_id,
       v.venue_id,
       ST_DistanceSphere(e.venue_geom, v.geom)                      AS distance_m,
       similarity(lower(coalesce(e.venue_name, '')), lower(v.name)) AS name_similarity
  FROM event e
  JOIN LATERAL (
       SELECT v.venue_id, v.name, v.geom
         FROM venue v
        ORDER BY e.venue_geom <-> v.geom
        LIMIT 1
  ) v ON true
 WHERE e.venue_geom IS NOT NULL
   AND (%(only_unmatched)s IS FALSE OR e.venue_id IS NULL)
"""

SQL_UPDATE = """
UPDATE event
   SET venue_id = %(venue_id)s,
       venue_match_basis = %(basis)s,
       venue_match_distance_m = %(distance_m)s
 WHERE event_id = %(event_id)s
"""

SQL_CLEAR = """
UPDATE event
   SET venue_id = NULL, venue_match_basis = 'none', venue_match_distance_m = NULL
"""

SQL_REPORT = """
SELECT venue_match_basis, count(*) AS n,
       round(avg(venue_match_distance_m))::int AS avg_distance_m
  FROM event
 GROUP BY venue_match_basis
 ORDER BY venue_match_basis
"""


def decide(distance_m: float, similarity: float) -> str:
    """The matching rule. Pure, so it can be unit tested without PostGIS."""
    if distance_m <= NAME_AND_DISTANCE_M and similarity > MIN_SIMILARITY:
        return "name_and_distance"
    if distance_m <= DISTANCE_ONLY_M:
        return "distance_only"
    if similarity >= STRONG_SIMILARITY and distance_m <= NAME_ONLY_M:
        return "name_only"
    return "none"


def match_events(conn: Any, *, only_unmatched: bool = True) -> dict[str, int]:
    """Fill venue_id on events. Returns the count per basis."""
    counts: dict[str, int] = {}
    rows = conn.execute(SQL_CANDIDATES, {"only_unmatched": only_unmatched}).fetchall()
    for row in rows:
        basis = decide(float(row["distance_m"]), float(row["name_similarity"]))
        counts[basis] = counts.get(basis, 0) + 1
        if basis == "none":
            conn.execute(
                SQL_UPDATE,
                {
                    "venue_id": None,
                    "basis": "none",
                    "distance_m": None,
                    "event_id": row["event_id"],
                },
            )
            continue
        conn.execute(
            SQL_UPDATE,
            {
                "venue_id": row["venue_id"],
                "basis": basis,
                "distance_m": round(float(row["distance_m"]), 1),
                "event_id": row["event_id"],
            },
        )
    return counts


def report(conn: Any) -> str:
    lines = ["  venue match:"]
    for row in conn.execute(SQL_REPORT).fetchall():
        avg = f", avg {row['avg_distance_m']} m" if row["avg_distance_m"] is not None else ""
        lines.append(f"    {row['venue_match_basis']:<18} {row['n']:>6}{avg}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--all", action="store_true", help="re-decide every event, not only unmatched")
    p.add_argument("--report", action="store_true", help="print the distribution and exit")
    a = p.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set.")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        if a.report:
            print(report(conn))
            return
        if a.all:
            conn.execute(SQL_CLEAR)
        counts = match_events(conn, only_unmatched=not a.all)
        conn.commit()
        print("  decided:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        print(report(conn))


if __name__ == "__main__":
    main()
