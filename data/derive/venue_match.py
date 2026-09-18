"""Match DS-09 places to DS-01 venues (data/sql/009, API contract v0.2 section 7).

The transformer leaves ``program_venue.venue_id`` empty on purpose: it never
decides whether two points are the same place. This module does, after the
load, in the derive stage like status_builder. It fills ``venue_id`` and
records the two pieces of evidence the decision rested on
(``match_distance_m`` and ``match_name_similarity``), so a matched programme
shows its venue's four access tiles and an unmatched one shows "no published
information" for all four.

THE RULE, AND WHY DISTANCE ALONE IS NOT ENOUGH

Against the 552 AAA Play places, the nearest DS-01 venue within 20 m was a
different place twice: a cafe 5 m from a gym, and netball courts 16 m from a
leisure centre they sit inside but are not. Both are honest neighbours and
wrong answers. So a match needs the name to agree as well:

    name_and_distance  within 150 m AND trigram similarity > 0.3  (the normal case)
    distance_only      within 25 m           (same point, names differ: "SportLink" vs
                                              "Sportlink Vermont South")
    name_only          similarity >= 0.6 AND within 400 m  (same name, pin on the car park)
    none               everything else; the programme is still listed

The verdict is not stored, only the evidence, so the thresholds can be
revisited without a reload; ``basis()`` re-derives the verdict from the two
numbers and the API uses the same function. Run with ``--report`` to print
the distribution the way the source assessment did.
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
SELECT p.program_venue_id,
       v.venue_id,
       ST_DistanceSphere(p.geom, v.geom)                       AS distance_m,
       similarity(lower(coalesce(p.name, '')), lower(v.name)) AS name_similarity
  FROM program_venue p
  JOIN LATERAL (
       SELECT v.venue_id, v.name, v.geom
         FROM venue v
        ORDER BY p.geom <-> v.geom
        LIMIT 1
  ) v ON true
 WHERE p.geom IS NOT NULL
   AND (%(only_unmatched)s IS FALSE OR p.venue_id IS NULL)
"""

SQL_UPDATE = """
UPDATE program_venue
   SET venue_id = %(venue_id)s,
       match_distance_m = %(distance_m)s,
       match_name_similarity = %(similarity)s
 WHERE program_venue_id = %(program_venue_id)s
"""

SQL_CLEAR = """
UPDATE program_venue
   SET venue_id = NULL, match_distance_m = NULL, match_name_similarity = NULL
"""

SQL_REPORT = """
SELECT venue_matched, count(*) AS n,
       round(avg(match_distance_m))::int AS avg_distance_m,
       round(avg(match_name_similarity)::numeric, 2) AS avg_similarity
  FROM program_venue
 GROUP BY venue_matched
 ORDER BY venue_matched DESC
"""


def basis(distance_m: float | None, similarity: float | None) -> str:
    """The matching rule. Pure, so it can be unit tested without PostGIS and
    reused by the API to name the basis of a stored match."""
    if distance_m is None or similarity is None:
        return "none"
    if distance_m <= NAME_AND_DISTANCE_M and similarity > MIN_SIMILARITY:
        return "name_and_distance"
    if distance_m <= DISTANCE_ONLY_M:
        return "distance_only"
    if similarity >= STRONG_SIMILARITY and distance_m <= NAME_ONLY_M:
        return "name_only"
    return "none"


def match_places(conn: Any, *, only_unmatched: bool = True) -> dict[str, int]:
    """Fill venue_id on program_venue. Returns the count per basis."""
    counts: dict[str, int] = {}
    rows = conn.execute(SQL_CANDIDATES, {"only_unmatched": only_unmatched}).fetchall()
    for row in rows:
        distance = float(row["distance_m"])
        similarity = float(row["name_similarity"])
        verdict = basis(distance, similarity)
        counts[verdict] = counts.get(verdict, 0) + 1
        conn.execute(
            SQL_UPDATE,
            {
                "venue_id": row["venue_id"] if verdict != "none" else None,
                "distance_m": round(distance, 1) if verdict != "none" else None,
                "similarity": round(similarity, 3) if verdict != "none" else None,
                "program_venue_id": row["program_venue_id"],
            },
        )
    return counts


def report(conn: Any) -> str:
    lines = ["  place match:"]
    for row in conn.execute(SQL_REPORT).fetchall():
        label = "matched" if row["venue_matched"] else "unmatched"
        detail = ""
        if row["avg_distance_m"] is not None:
            detail = f", avg {row['avg_distance_m']} m, avg similarity {row['avg_similarity']}"
        lines.append(f"    {label:<10} {row['n']:>6}{detail}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--all", action="store_true", help="re-decide every place, not only unmatched")
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
        counts = match_places(conn, only_unmatched=not a.all)
        conn.commit()
        print("  decided:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        print(report(conn))


if __name__ == "__main__":
    main()
