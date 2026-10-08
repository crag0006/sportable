"""Derive a suburb and a postcode for every DS-09 place from its coordinates
(data/sql/010_program_venue_geography.sql).

WHY THIS EXISTS

AAA Play publishes 552 places and geocodes all 552 of them, but only 288
(52.2%) carry a parsed post_code / city / state_short as well. The other 264
have a free-text address and a point. ``009`` stores what the publisher
published, so those 264 rows have a NULL suburb_name and a NULL postcode, and
every query that pairs the two — including the places dropdown behind the
required Suburb/Postcode field in AC4.1.1 — drops them silently. They are not
mislabelled; they are unreachable.

A point inside an ABS boundary is a fact with a published polygon behind it.
This module asserts that fact and nothing more: it runs the containment test
against ``suburb`` (DS-07) and ``postal_area`` (DS-08), both EPSG:7844, the same
CRS as the point, and writes the result to ``program_venue.derived_*``.

WHAT IT REFUSES TO DO

*   It never overwrites a publisher value. ``suburb_name``, ``postcode`` and
    ``full_address`` stay exactly as DS-09 published them, because the address
    is what a human reads. The derived codes are what the query matches.
*   It never invents a positive. A point that falls inside no polygon derives
    NULL, ``derived_at`` still records that the test ran, and that is the whole
    answer. There is no nearest-polygon fallback, because "the nearest suburb to
    this point" is a different claim from "this point is in this suburb".

THE CROSS-CHECK

For the 288 places that have both a published and a derived value, the two are
independent statements about the same place: what the provider typed, and where
the provider's own geocode falls. A disagreement means one of them is wrong, and
which one cannot be settled from here. So the rate is reported rather than
resolved, and ``--report`` prints the offending rows by name so a person can
look at them. A disagreement rate is not something to average away: a handful of
rows is a data-entry story, and a large block is a geocoding story, and the two
need different people.

The counts are returned and logged rather than written to ``load_run``. A
``load_run`` row describes one source's load; this runs after the load, across
every row the table holds including rows an earlier run wrote, so it has no one
run to belong to. ``status_builder`` reports the same way for the same reason.

USAGE

    export DATABASE_URL=postgresql://...@localhost:5433/sportable
    uv run python derive/place_geography.py            # derive the new rows, refresh
    uv run python derive/place_geography.py --all      # re-derive every row
    uv run python derive/place_geography.py --report   # print coverage, change nothing
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

LOG = logging.getLogger("sportable.place_geography")

# The read model the dropdown reads. Created in 010; refreshed here because the
# DS-09 derive stage is not yet part of the pipeline run that
# status_builder.refresh_read_model() drives. When it is, this view belongs in
# status_builder.READ_MODEL_VIEWS and this function can go.
PLACE_VOCABULARY = "place_vocabulary"

# Below this share of agreement, the cross-check is telling us something about
# the source rather than about a few typos, and a person should look before the
# derived values are trusted for anything but search. It is a review trigger and
# deliberately not a gate: refusing to publish 552 places because 90% of the
# addresses agree instead of 95% would help nobody.
AGREEMENT_FLOOR = 0.95

# How many disagreeing rows --report prints before it stops. Enough to see the
# shape of the problem; the view holds all of them for anyone who wants more.
DISAGREEMENT_SAMPLE = 20

# The ABS disambiguating suffix on duplicated locality names: "Preston (Vic.)",
# "Melton (Melton - Vic.)". The API strips the same suffix with the same pattern
# before matching a typed name (PLAIN_LABEL in backend/app/repositories/
# postgres.py) and so does the program_venue_geography_check view in 010. Three
# copies of one rule is two too many, so if this pattern ever changes, change it
# in all three.
ABS_SUFFIX = re.compile(r"\s*\([^)]*\)$")


# ---------------------------------------------------------------------------
# SQL
#
# The work happens in PostGIS, not in Python. A containment test against a GiST
# index is one statement; pulling 552 points and 3,000 polygons into shapely to
# do the same thing would be slower, would need the geometry column shipped over
# the wire, and would put the answer somewhere the database cannot constrain it.
# ---------------------------------------------------------------------------

# only_new is how the run stays cheap on a re-run: derived_at IS NULL is exactly
# the set that has never been tested. Passing only_new = False re-derives
# everything, which is what to do after a boundary layer is reloaded.
#
# Rows with no geocode are excluded rather than marked: they have nothing to test
# against, so derived_at stays NULL and says so.
SQL_DERIVE = """
UPDATE program_venue pv
   SET derived_suburb_code = g.suburb_code,
       derived_suburb_name = g.suburb_name,
       derived_postcode    = g.poa_code,
       derived_at          = now()
  FROM (
        SELECT p.program_venue_id,
               sb.suburb_code,
               sb.suburb_name,
               pa.poa_code
          FROM program_venue p
          LEFT JOIN LATERAL (
                SELECT s.suburb_code, s.suburb_name
                  FROM suburb s
                 WHERE ST_Contains(s.geom, p.geom)
                 ORDER BY s.suburb_code
                 LIMIT 1
          ) sb ON true
          LEFT JOIN LATERAL (
                SELECT a.poa_code
                  FROM postal_area a
                 WHERE ST_Contains(a.geom, p.geom)
                 ORDER BY a.poa_code
                 LIMIT 1
          ) pa ON true
         WHERE p.geom IS NOT NULL
           AND (%(only_new)s IS FALSE OR p.derived_at IS NULL)
  ) g
 WHERE pv.program_venue_id = g.program_venue_id
"""

SQL_COVERAGE = """
SELECT count(*)                                                     AS places,
       count(*) FILTER (WHERE geom IS NOT NULL)                     AS geocoded,
       count(*) FILTER (WHERE derived_at IS NOT NULL)               AS attempted,
       count(*) FILTER (WHERE derived_suburb_code IS NOT NULL)      AS suburb_derived,
       count(*) FILTER (WHERE derived_postcode IS NOT NULL)         AS postcode_derived,
       count(*) FILTER (WHERE derived_suburb_code IS NOT NULL
                          AND derived_postcode IS NOT NULL)         AS pair_derived,
       count(*) FILTER (WHERE suburb_name IS NOT NULL
                          AND postcode IS NOT NULL)                 AS pair_published,
       count(*) FILTER (WHERE geom IS NOT NULL
                          AND (derived_suburb_code IS NULL
                               OR derived_postcode IS NULL))        AS geocoded_without_pair
  FROM program_venue
"""

# FILTER (WHERE suburb_agrees) counts only true: a NULL means one side said
# nothing, which is not a disagreement and must not be counted as one.
SQL_AGREEMENT = """
SELECT count(*) FILTER (WHERE suburb_agrees IS NOT NULL)   AS suburb_comparable,
       count(*) FILTER (WHERE suburb_agrees)               AS suburb_agreed,
       count(*) FILTER (WHERE postcode_agrees IS NOT NULL) AS postcode_comparable,
       count(*) FILTER (WHERE postcode_agrees)             AS postcode_agreed
  FROM program_venue_geography_check
"""

SQL_DISAGREEMENTS = """
SELECT program_venue_id,
       name,
       full_address,
       published_suburb,
       derived_suburb_name,
       published_postcode,
       derived_postcode
  FROM program_venue_geography_check
 WHERE suburb_agrees IS FALSE
    OR postcode_agrees IS FALSE
 ORDER BY program_venue_id
 LIMIT %(limit)s
"""


# ---------------------------------------------------------------------------
# Pure helpers
#
# Separated from the SQL so the rules can be tested without a database, which is
# the only way the data tests stay runnable in CI.
# ---------------------------------------------------------------------------


def normalise_suburb_name(name: str | None) -> str | None:
    """Fold a suburb name to the form the two sides are compared on.

    The publisher types "Preston"; the ABS publishes "Preston (Vic.)". They are
    the same suburb and must not be counted as a disagreement. Returns None for
    None, because an absent name normalises to an absent name and not to "".
    """
    if name is None:
        return None
    return ABS_SUFFIX.sub("", name).strip().lower()


def agreement_rate(agreed: int, comparable: int) -> float | None:
    """The share of comparable rows that agree, or None when nothing is
    comparable.

    None, not 1.0 and not 0.0. With no rows carrying both values there is no
    evidence either way, and reporting a rate of 100% for an empty set is
    exactly the kind of invented positive this pipeline is built to avoid.
    """
    if comparable <= 0:
        return None
    return agreed / comparable


def needs_review(rate: float | None, floor: float = AGREEMENT_FLOOR) -> bool:
    """Whether the agreement rate is low enough to want a person.

    An unknown rate does not need review; it needs data. Saying otherwise would
    raise an alarm on every empty database.
    """
    return rate is not None and rate < floor


def _percent(rate: float | None) -> str:
    return "not comparable" if rate is None else f"{round(100 * rate, 1)}%"


@dataclass
class GeographyOutcome:
    """What one run did and what the data looks like afterwards."""

    rows_derived: int

    places: int
    geocoded: int
    attempted: int
    suburb_derived: int
    postcode_derived: int
    pair_derived: int
    pair_published: int
    geocoded_without_pair: int

    suburb_comparable: int
    suburb_agreed: int
    postcode_comparable: int
    postcode_agreed: int

    @property
    def suburb_agreement(self) -> float | None:
        return agreement_rate(self.suburb_agreed, self.suburb_comparable)

    @property
    def postcode_agreement(self) -> float | None:
        return agreement_rate(self.postcode_agreed, self.postcode_comparable)

    @property
    def wants_review(self) -> bool:
        return needs_review(self.suburb_agreement) or needs_review(self.postcode_agreement)

    def summary(self) -> str:
        """The block that goes in the quality report, in the shape
        status_builder.StatusOutcome.summary() uses."""
        reachable_before = self.pair_published
        reachable_after = self.pair_derived

        lines = [
            "Place geography (DS-09 suburb and postcode, derived)",
            f"  places                     {self.places:,}",
            f"  geocoded                   {self.geocoded:,}",
            f"  point-in-polygon ran on    {self.attempted:,}",
            f"  rows written this run      {self.rows_derived:,}",
            f"  suburb derived             {self.suburb_derived:,}",
            f"  postcode derived           {self.postcode_derived:,}",
            f"  suburb + postcode derived  {self.pair_derived:,}",
            f"  suburb + postcode as published {reachable_before:,}",
            f"  searchable pairs before/after  {reachable_before:,} -> {reachable_after:,}",
        ]

        # Surfaced, not swallowed. A geocoded place with no derived pair is a
        # place the dropdown still cannot reach, and the number is the honest
        # measure of how far this got.
        if self.geocoded_without_pair:
            lines.append(
                f"  STILL UNREACHABLE          {self.geocoded_without_pair:,} "
                "geocoded places fall outside one of the two boundary layers"
            )

        lines += [
            "  agreement with the publisher, where both exist",
            f"    suburb    {self.suburb_agreed:,}/{self.suburb_comparable:,} "
            f"= {_percent(self.suburb_agreement)}",
            f"    postcode  {self.postcode_agreed:,}/{self.postcode_comparable:,} "
            f"= {_percent(self.postcode_agreement)}",
        ]

        if self.wants_review:
            lines.append(
                f"    BELOW THE {round(100 * AGREEMENT_FLOOR)}% FLOOR — the address and the "
                "geocode disagree often enough that one of them is systematically wrong. "
                "Run with --report and read the rows before trusting either."
            )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Database work
# ---------------------------------------------------------------------------


def derive(conn: Any, *, only_new: bool = True) -> int:
    """Run the containment test and write the derived columns. Returns the
    number of rows written."""
    cur = conn.execute(SQL_DERIVE, {"only_new": only_new})
    written = int(cur.rowcount or 0)
    LOG.info("derived geography for %s places (only_new=%s)", written, only_new)
    return written


def coverage(conn: Any) -> dict[str, int]:
    """How much of the table now carries each value."""
    row = conn.execute(SQL_COVERAGE).fetchone()
    return {k: int(v or 0) for k, v in row.items()}


def agreement(conn: Any) -> dict[str, int]:
    """Published against derived, for the rows that carry both."""
    row = conn.execute(SQL_AGREEMENT).fetchone()
    return {k: int(v or 0) for k, v in row.items()}


def disagreements(conn: Any, limit: int = DISAGREEMENT_SAMPLE) -> list[dict[str, Any]]:
    """The rows where the publisher's address and the publisher's geocode
    contradict each other, named so a person can look at them."""
    return list(conn.execute(SQL_DISAGREEMENTS, {"limit": limit}).fetchall())


def refresh_place_vocabulary(conn: Any) -> None:
    """Refresh the dropdown's read model.

    CONCURRENTLY so the API keeps serving during a pipeline run, with the same
    blocking fallback status_builder.refresh_read_model() uses: the concurrent
    form cannot run against a materialised view that has never been populated,
    which is exactly the state the first run after 010 finds it in.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {PLACE_VOCABULARY}")
    except Exception as error:
        LOG.warning(
            "Concurrent refresh of %s failed (%s). Falling back to a blocking "
            "refresh, which is expected on the first run after 010.",
            PLACE_VOCABULARY,
            error,
        )
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(f"REFRESH MATERIALIZED VIEW {PLACE_VOCABULARY}")

    LOG.info("refreshed %s", PLACE_VOCABULARY)


def build(conn: Any, *, only_new: bool = True, refresh: bool = True) -> GeographyOutcome:
    """Derive, refresh the read model, and report. The one entry point a caller
    needs; the pieces above are separate so a report can be printed without
    writing anything."""
    written = derive(conn, only_new=only_new)

    if refresh:
        refresh_place_vocabulary(conn)

    return report(conn, rows_derived=written)


def report(conn: Any, *, rows_derived: int = 0) -> GeographyOutcome:
    """Read the counts back out of the database. Writes nothing."""
    counts = coverage(conn)
    agreed = agreement(conn)

    return GeographyOutcome(
        rows_derived=rows_derived,
        places=counts["places"],
        geocoded=counts["geocoded"],
        attempted=counts["attempted"],
        suburb_derived=counts["suburb_derived"],
        postcode_derived=counts["postcode_derived"],
        pair_derived=counts["pair_derived"],
        pair_published=counts["pair_published"],
        geocoded_without_pair=counts["geocoded_without_pair"],
        suburb_comparable=agreed["suburb_comparable"],
        suburb_agreed=agreed["suburb_agreed"],
        postcode_comparable=agreed["postcode_comparable"],
        postcode_agreed=agreed["postcode_agreed"],
    )


def _format_disagreements(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "  no disagreements between the published values and the derived ones"

    lines = ["  published against derived, where they differ:"]

    for row in rows:
        lines.append(
            f"    {row['program_venue_id']}  {row['name']}\n"
            f"      address   {row['full_address']}\n"
            f"      published {row['published_suburb']} {row['published_postcode']}\n"
            f"      derived   {row['derived_suburb_name']} {row['derived_postcode']}"
        )

    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="re-derive every place, not only the ones never tested",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="print coverage and the disagreements, and change nothing",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="skip the place_vocabulary refresh (for a run inside a larger job)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DISAGREEMENT_SAMPLE,
        help=f"how many disagreeing rows to print (default {DISAGREEMENT_SAMPLE})",
    )
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL")

    if not url:
        sys.exit("DATABASE_URL is not set.")

    with psycopg.connect(url, row_factory=dict_row) as conn:
        if args.report:
            print(report(conn).summary())
            print(_format_disagreements(disagreements(conn, args.limit)))
            return

        outcome = build(conn, only_new=not args.all, refresh=not args.no_refresh)
        conn.commit()

        print(outcome.summary())
        print(_format_disagreements(disagreements(conn, args.limit)))


if __name__ == "__main__":
    main()
