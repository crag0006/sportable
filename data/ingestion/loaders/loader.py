"""
ingestion/loaders/loader.py

Handles writes into the serving database.

This is the only layer that talks directly to the database. The transformers
above it prepare the data without needing database access.

The loader handles three main things:

- Checking that records are inside the Greater Melbourne boundary.
- Writing records in an idempotent way so the pipeline can be rerun safely.
- Stopping the load if too many rows are quarantined.

Rejected rows go to TWO places, and the reason is the abort path. The
``quarantine`` table is the better home for a load that commits: a person
diagnosing a bad transform wants SQL. But ``write_quarantine`` inserts inside
the load transaction, ``check_rejection_rate`` raises above the threshold, and
``connect`` rolls back on any exception — so on the one path where the rows
matter most, they are discarded with everything else. The optional
``quarantine_sink`` writes them somewhere outside the transaction first.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd
import psycopg
from psycopg.rows import dict_row

LOG = logging.getLogger("sportable.loader")

# CRS used by the serving database.
SRID = 7844

# A load that rejects more than this share of its in-scope rows stops. Raising a
# threshold to accommodate a bad load defeats its purpose, so these are set from
# each publisher's DOCUMENTED coverage and cite where the number comes from.
MAX_QUARANTINE_RATE_PCT = 15.0

# Per-source overrides, for publishers whose known coverage exceeds the default.
#
# DS-01: the source card records "The 129 in-area rows resolve to 52 distinct
# venues by name and full address, of which 38 carry coordinates" — 14 of 52,
# or 26.92%, have no published coordinates and are quarantined as COORD_MISSING.
# A first load against staging on 1 Sep 2026 produced exactly 52 in scope, 38
# loaded and 14 quarantined, matching the card to the row.
#
# The previous comment here put the DS-01 baseline at 9.09%, which is what the
# 15% default was calibrated against. That figure disagrees with the card and
# with the observed load; 30% sits above the documented 26.92% and still well
# below anything that would indicate a broken contract.
#
# This is NOT a licence to raise a number until a load passes. If DS-01 ever
# exceeds 30%, the publisher's coverage has changed and the card needs
# re-profiling — the guard has done its job and should stop the load.
MAX_QUARANTINE_RATE_BY_SOURCE = {
    "DS-01": 30.0,
}


class LoadAbortedError(RuntimeError):
    """Raised when a load exceeds the quarantine threshold."""


@dataclass
class LoadOutcome:
    load_run_id: int
    source_id: str
    rows_read: int
    rows_loaded: int
    rows_quarantined: int
    quarantine_rate_pct: float
    outside_scope: int

    def __str__(self) -> str:
        return (
            f"{self.source_id} run {self.load_run_id}: "
            f"{self.rows_loaded:,} loaded, {self.rows_quarantined:,} quarantined "
            f"({self.quarantine_rate_pct}%), {self.outside_scope:,} outside scope"
        )


# Connection


@contextmanager
def connect(dsn: str):
    """Open a database connection and handle commit/rollback."""

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# Run lifecycle


def open_load_run(
    conn,
    source_id: str,
    dt_partition: str,
    raw_object_key: str,
    raw_sha256: str,
) -> int:
    """Create a load run and return its id."""

    row = conn.execute(
        """
        INSERT INTO load_run (source_id, dt_partition, raw_object_key, raw_sha256)
        VALUES (%s, %s, %s, %s)
        RETURNING load_run_id
        """,
        (source_id, dt_partition, raw_object_key, raw_sha256),
    ).fetchone()

    return row["load_run_id"]


def close_load_run(
    conn,
    load_run_id: int,
    rows_read: int,
    rows_loaded: int,
    rows_quarantined: int,
    outcome: str,
    rows_outside_scope: int = 0,
) -> None:

    conn.execute(
        """
        UPDATE load_run
           SET completed_at = now(),
               rows_read = %s,
               rows_loaded = %s,
               rows_quarantined = %s,
               rows_outside_scope = %s,
               outcome = %s
         WHERE load_run_id = %s
        """,
        (
            rows_read,
            rows_loaded,
            rows_quarantined,
            rows_outside_scope,
            outcome,
            load_run_id,
        ),
    )


# Scope


def greater_melbourne_wkb(conn) -> bytes | None:
    """Return the union of the 31 Greater Melbourne councils."""

    row = conn.execute(
        """
        SELECT ST_AsBinary(ST_Union(geom)) AS wkb
          FROM lga
         WHERE in_greater_melbourne
        """
    ).fetchone()

    return row["wkb"] if row and row["wkb"] else None


def clip_to_scope(
    conn,
    frame: pd.DataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split records into Greater Melbourne and outside-scope rows."""

    if frame.empty:
        return frame, frame

    row = conn.execute("SELECT count(*) AS n FROM lga WHERE in_greater_melbourne").fetchone()

    if not row or row["n"] == 0:
        raise RuntimeError(
            "The LGA boundary layer is empty, so scope cannot be decided. "
            "Load DS-06 before loading any source that needs clipping."
        )

    points = [
        (int(i), float(r[lon_col]), float(r[lat_col]))
        for i, r in frame.iterrows()
        if pd.notna(r[lat_col]) and pd.notna(r[lon_col])
    ]

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TEMP TABLE _scope_check (
                idx integer,
                lon double precision,
                lat double precision
            ) ON COMMIT DROP
            """
        )

        with cur.copy("COPY _scope_check (idx, lon, lat) FROM STDIN") as copy:
            for record in points:
                copy.write_row(record)

        cur.execute(
            f"""
            SELECT c.idx
              FROM _scope_check c
             WHERE EXISTS (
                   SELECT 1
                     FROM lga l
                    WHERE l.in_greater_melbourne
                      AND ST_Intersects(
                          l.geom,
                          ST_SetSRID(
                              ST_MakePoint(c.lon, c.lat),
                              {SRID}
                          )
                      )
             )
            """
        )

        inside = {r["idx"] for r in cur.fetchall()}

        cur.execute("DROP TABLE IF EXISTS _scope_check")

    mask = frame.index.map(lambda i: int(i) in inside)

    return (
        frame[mask],
        frame[~pd.Series(mask, index=frame.index)],
    )


# Writes


def _upsert(
    conn,
    table: str,
    columns: Sequence[str],
    key_columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    geometry_from: tuple[str, str] | None = None,
) -> int:
    """Insert or update rows using the supplied key columns."""

    rows = list(rows)

    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(columns))
    target_columns = list(columns)
    values_expression = placeholders

    if geometry_from:
        lon_col, lat_col = geometry_from

        lon_i = columns.index(lon_col)
        lat_i = columns.index(lat_col)

        target_columns = [c for c in columns if c not in (lon_col, lat_col)] + ["geom"]

        parts = ["%s" for c in columns if c not in (lon_col, lat_col)]

        # Put longitude and latitude at the end because they are used
        # to create the geometry in SQL.
        reordered = []

        for r in rows:
            keep = [v for i, v in enumerate(r) if i not in (lon_i, lat_i)]

            keep += [r[lon_i], r[lat_i]]
            reordered.append(keep)

        rows = reordered
        values_expression = ", ".join(
            [
                *parts,
                f"ST_SetSRID(ST_MakePoint(%s, %s), {SRID})",
            ]
        )

    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in target_columns if c not in key_columns)

    sql = f"""
        INSERT INTO {table} ({", ".join(target_columns)})
        VALUES ({values_expression})
        ON CONFLICT ({", ".join(key_columns)})
        DO UPDATE SET {updates}
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    return len(rows)


class QuarantineSink(Protocol):
    """Somewhere outside the database to put rejected rows.

    Implemented by the Lambda handler over S3. Kept as a protocol so this module
    keeps its one dependency on psycopg and never imports boto3 — the handler
    owns AWS, this layer owns the database.
    """

    def __call__(self, *, load_run_id: int, source_id: str, frame: pd.DataFrame) -> str | None: ...


def write_quarantine(
    conn,
    load_run_id: int,
    source_id: str,
    frame: pd.DataFrame,
    sink: QuarantineSink | None = None,
) -> int:
    """Store rejected rows in the quarantine table, and in ``sink`` if given.

    The sink is written FIRST and its failure is never allowed to fail the load.
    Losing the evidence is bad; losing the load because the evidence could not be
    filed is worse, and the table write still happens either way.
    """

    if frame.empty:
        return 0

    if sink is not None:
        try:
            sink(load_run_id=load_run_id, source_id=source_id, frame=frame)
        except Exception:  # deliberately broad - see the docstring
            LOG.exception(
                "Could not write %s rejected rows to the quarantine sink. "
                "Continuing: the table write below is unaffected.",
                len(frame),
            )

    records = [
        (
            load_run_id,
            source_id,
            row.get("natural_key"),
            row["reason"],
            row.get("detail"),
            json.dumps(
                row.get("payload") or {},
                default=str,
            ),
        )
        for _, row in frame.iterrows()
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO quarantine
                (load_run_id, source_id, natural_key, reason, detail, payload)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            records,
        )

    return len(records)


def check_rejection_rate(
    source_id: str,
    loaded: int,
    quarantined: int,
) -> float:
    """Check the quarantine rate and stop the load if it is too high."""

    # Only rows that were in scope are included in this calculation.
    total = loaded + quarantined

    if total == 0:
        return 0.0
    rate = round(100 * quarantined / total, 2)
    threshold = MAX_QUARANTINE_RATE_BY_SOURCE.get(source_id, MAX_QUARANTINE_RATE_PCT)
    if rate > threshold:
        raise LoadAbortedError(
            f"{source_id} quarantined {quarantined:,} of {total:,} rows ({rate}%), "
            f"above the {threshold}% threshold. The load has been "
            f"abandoned. The rows are in the quarantine BUCKET, not the "
            f"quarantine table: this abort rolls the transaction back. Inspect "
            f"them before rerunning; do not raise the threshold to make this "
            f"pass."
        )

    return rate


# Source-specific loads


VENUE_COLUMNS = [
    "venue_id",
    "source_id",
    "load_run_id",
    "name",
    "full_address",
    "suburb_name",
    "postcode",
    "lga_name",
    "ownership",
    "purpose",
    "changeroom_description",
    "onsite_accessible_toilet",
    "onsite_accessible_parking",
    "retrieved_at",
    "longitude",
    "latitude",
]

AMENITY_COLUMNS = [
    "amenity_id",
    "source_id",
    "load_run_id",
    "kind",
    "name",
    "address",
    "key_required",
    "mlak_24h",
    "payment_required",
    "opening_hours",
    "access_note",
    "facility_note",
    "is_inside_venue",
    "key_is_derived",
    "changing_places",
    "byo_sling",
    "has_shower",
    "ambulant",
    "left_hand_transfer",
    "right_hand_transfer",
    "accessible_parking_on_site",
    # DS-03 only. Null for other sources.
    "transport_mode",
    "wheelchair_boarding",
    "stop_code",
    "retrieved_at",
    "longitude",
    "latitude",
]

POSTAL_AREA_COLUMNS = [
    "poa_code",
    "poa_name",
    "source_id",
]


def _tuples(
    frame: pd.DataFrame,
    columns: Sequence[str],
) -> list[tuple]:
    """Convert a DataFrame into tuples matching the target columns."""

    out = []

    for _, row in frame.iterrows():
        record = []

        for c in columns:
            value = row.get(c)

            if (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
                value = None

            elif hasattr(value, "item") and not isinstance(
                value,
                (str, bytes),
            ):
                with suppress(Exception):
                    value = value.item()

            record.append(value)

        out.append(tuple(record))

    return out


def load_venues(
    conn,
    load_run_id: int,
    source_id: str,
    venues: pd.DataFrame,
    venue_sports: pd.DataFrame,
    quarantine: pd.DataFrame,
    rows_read: int,
    sink: QuarantineSink | None = None,
) -> LoadOutcome:
    """Load venues and their associated sports."""

    kept, rejected = clip_to_scope(
        conn,
        venues,
    )

    loaded = _upsert(
        conn,
        "venue",
        VENUE_COLUMNS,
        ["venue_id"],
        _tuples(kept, VENUE_COLUMNS),
        geometry_from=("longitude", "latitude"),
    )

    # Replace sport rows for the venues in this batch so removed sports
    # do not remain from an older load.
    if loaded and not venue_sports.empty:
        ids = tuple(kept["venue_id"].tolist())

        sports = venue_sports[venue_sports["venue_id"].isin(kept["venue_id"])]

        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM venue_sport WHERE venue_id = ANY(%s)",
                (list(ids),),
            )

            cur.executemany(
                """
                INSERT INTO venue_sport
                    (venue_id, sport, court_count, surface_type)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (venue_id, sport, surface_type) DO NOTHING
                """,
                _tuples(
                    sports,
                    [
                        "venue_id",
                        "sport",
                        "court_count",
                        "surface_type",
                    ],
                ),
            )

    quarantined = write_quarantine(
        conn,
        load_run_id,
        source_id,
        quarantine,
        sink=sink,
    )

    rate = check_rejection_rate(
        source_id,
        loaded,
        quarantined,
    )

    return LoadOutcome(
        load_run_id=load_run_id,
        source_id=source_id,
        rows_read=rows_read,
        rows_loaded=loaded,
        rows_quarantined=quarantined,
        quarantine_rate_pct=rate,
        outside_scope=len(rejected),
    )


def load_postal_areas(
    conn,
    load_run_id: int,
    source_id: str,
    postal_areas: pd.DataFrame,
    quarantine: pd.DataFrame,
    rows_read: int,
    sink: QuarantineSink | None = None,
) -> LoadOutcome:
    """Load the DS-08 postal area data."""

    if postal_areas.empty:
        raise RuntimeError(
            f"{source_id} produced no postal areas. The search resolver "
            "cannot be built and the load must not complete."
        )

    records = [
        (
            row["poa_code"],
            row["poa_name"],
            source_id,
            row["wkt"],
        )
        for _, row in postal_areas.iterrows()
    ]

    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO postal_area
                (poa_code, poa_name, source_id, geom)
            VALUES (
                %s,
                %s,
                %s,
                ST_Multi(
                    ST_SetSRID(
                        ST_GeomFromText(%s),
                        {SRID}
                    )
                )
            )
            ON CONFLICT (poa_code) DO UPDATE
               SET poa_name  = EXCLUDED.poa_name,
                   source_id = EXCLUDED.source_id,
                   geom      = EXCLUDED.geom
            """,
            records,
        )

    quarantined = write_quarantine(
        conn,
        load_run_id,
        source_id,
        quarantine,
        sink=sink,
    )

    rate = check_rejection_rate(
        source_id,
        len(records),
        quarantined,
    )

    return LoadOutcome(
        load_run_id=load_run_id,
        source_id=source_id,
        rows_read=rows_read,
        rows_loaded=len(records),
        rows_quarantined=quarantined,
        quarantine_rate_pct=rate,
        outside_scope=0,
    )


def load_amenities(
    conn,
    load_run_id: int,
    source_id: str,
    amenities: pd.DataFrame,
    quarantine: pd.DataFrame,
    rows_read: int,
    sink: QuarantineSink | None = None,
) -> LoadOutcome:
    """Load DS-02, DS-03 or DS-04 amenity data."""

    kept, rejected = clip_to_scope(
        conn,
        amenities,
    )

    loaded = _upsert(
        conn,
        "amenity",
        AMENITY_COLUMNS,
        ["amenity_id"],
        _tuples(kept, AMENITY_COLUMNS),
        geometry_from=("longitude", "latitude"),
    )

    quarantined = write_quarantine(
        conn,
        load_run_id,
        source_id,
        quarantine,
        sink=sink,
    )

    rate = check_rejection_rate(
        source_id,
        loaded,
        quarantined,
    )

    return LoadOutcome(
        load_run_id=load_run_id,
        source_id=source_id,
        rows_read=rows_read,
        rows_loaded=loaded,
        rows_quarantined=quarantined,
        quarantine_rate_pct=rate,
        outside_scope=len(rejected),
    )


# ---------------------------------------------------------------------------
# DS-09 programs
#
# APPEND THIS BLOCK TO ingestion/loaders/loader.py, after load_amenities.
# It uses _upsert, _tuples, clip_to_scope, write_quarantine,
# check_rejection_rate and LoadOutcome, all already defined in that file.
# ---------------------------------------------------------------------------

PROGRAM_ORGANISATION_COLUMNS = [
    "organisation_id",
    "source_id",
    "load_run_id",
    "publisher_key",
    "name",
    "website_url",
    "source_url",
    "publisher_last_updated",
    "retrieved_at",
]

PROGRAM_VENUE_COLUMNS = [
    "program_venue_id",
    "source_id",
    "load_run_id",
    "publisher_key",
    "name",
    "full_address",
    "suburb_name",
    "postcode",
    "publisher_lga_label",
    "latitude",
    "longitude",
    "publisher_place_ref",
    "accessible_car_spaces",
    "website_url",
    "source_url",
    "publisher_last_updated",
    "retrieved_at",
    "venue_id",
    "match_distance_m",
    "match_name_similarity",
]

# venue_matched is absent on purpose. It is GENERATED ALWAYS in the database,
# and naming a generated column in an INSERT is an error.
PROGRAM_VENUE_ATTRIBUTE_COLUMNS = [
    "program_venue_id",
    "attribute_key",
    "attribute_label",
    "source_id",
    "load_run_id",
]

PROGRAM_COLUMNS = [
    "program_id",
    "source_id",
    "load_run_id",
    "publisher_key",
    "name",
    "description",
    "starts_at",
    "ends_at",
    "recurrence_weekdays",
    "recurrence_time_of_day",
    "is_free",
    "price_label",
    "age_ranges",
    "welcoming",
    "environment",
    "program_venue_id",
    "organisation_id",
    "latitude",
    "longitude",
    "publisher_lga_label",
    "publisher_region_label",
    "registration_url",
    "source_url",
    "publisher_last_updated",
    "retrieved_at",
]

# `kind` is omitted so the column default of 'program' applies. DS-09 publishes
# nothing else, and spelling it out here would be the first place somebody
# changed when they wanted to force a dated row through.
PROGRAM_ACCESS_NEED_COLUMNS = [
    "program_id",
    "access_need_key",
    "access_need_label",
    "source_id",
    "load_run_id",
]

PROGRAM_SPORT_COLUMNS = [
    "program_id",
    "sport_key",
    "sport_label",
    "source_id",
    "load_run_id",
]


def _replace_children(
    conn,
    table: str,
    parent_column: str,
    parent_ids: Sequence[str],
    columns: Sequence[str],
    frame: pd.DataFrame,
) -> int:
    """Delete a parent's tag rows, then insert the current set.

    WHY NOT AN UPSERT. An upsert adds and updates but never removes. If a
    provider deletes the wheelchair tag from a programme, an upsert leaves
    yesterday's row in place and the site goes on claiming a published yes that
    the publisher has withdrawn. For a product whose whole argument is that it
    reports what the publisher actually says, a stale positive is the worst
    shape of error available.

    The delete is scoped to the parents in this payload, so a partial load
    cannot clear tags belonging to rows it did not touch.
    """
    if not parent_ids:
        return 0

    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {table} WHERE {parent_column} = ANY(%s)",
            (list(parent_ids),),
        )

    if frame.empty:
        return 0

    rows = _tuples(frame, columns)

    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(columns))

    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            rows,
        )

    return len(rows)


def load_programs(
    conn,
    load_run_id: int,
    source_id: str,
    result,
    rows_read: int,
    sink: QuarantineSink | None = None,
) -> LoadOutcome:
    """Load DS-09 programmes, their places, providers and tags.

    `result` is the TransformResult returned by ds09_aaaplay.transform.

    SCOPE IS DECIDED ON THE PROGRAMME, NOT THE PLACE. The programme is what a
    person searches for, so it is the thing clipped against the boundary. The
    places, providers and tags that come with it are then selected by reference
    from the programmes that survived, rather than being clipped separately.
    Clipping them independently would let a place fall outside the boundary
    while the programme standing on it fell inside, which leaves the programme
    pointing at a row that was never inserted and fails the whole load on a
    foreign key.

    INSERT ORDER FOLLOWS THE FOREIGN KEYS: providers and places first, because
    a programme references both; tags last, because they reference a programme.
    """
    kept, rejected = clip_to_scope(conn, result.programs)

    # Everything else is selected by reference from the programmes that survived.
    program_ids = list(kept["program_id"]) if len(kept) else []

    venue_ids = {v for v in kept["program_venue_id"] if isinstance(v, str)} if len(kept) else set()
    organisation_ids = (
        {o for o in kept["organisation_id"] if isinstance(o, str)} if len(kept) else set()
    )

    venues = result.program_venues
    venues = venues[venues["program_venue_id"].isin(venue_ids)] if len(venues) else venues

    organisations = result.organisations
    organisations = (
        organisations[organisations["organisation_id"].isin(organisation_ids)]
        if len(organisations)
        else organisations
    )

    attributes = result.venue_attributes
    attributes = (
        attributes[attributes["program_venue_id"].isin(venue_ids)]
        if len(attributes)
        else attributes
    )

    needs = result.program_access_needs
    needs = needs[needs["program_id"].isin(program_ids)] if len(needs) else needs

    sports = result.program_sports
    sports = sports[sports["program_id"].isin(program_ids)] if len(sports) else sports

    _upsert(
        conn,
        "program_organisation",
        PROGRAM_ORGANISATION_COLUMNS,
        ["organisation_id"],
        _tuples(organisations, PROGRAM_ORGANISATION_COLUMNS),
    )

    _upsert(
        conn,
        "program_venue",
        PROGRAM_VENUE_COLUMNS,
        ["program_venue_id"],
        _tuples(venues, PROGRAM_VENUE_COLUMNS),
        geometry_from=("longitude", "latitude"),
    )

    _replace_children(
        conn,
        "program_venue_attribute",
        "program_venue_id",
        sorted(venue_ids),
        PROGRAM_VENUE_ATTRIBUTE_COLUMNS,
        attributes,
    )

    loaded = _upsert(
        conn,
        "program",
        PROGRAM_COLUMNS,
        ["program_id"],
        _tuples(kept, PROGRAM_COLUMNS),
        geometry_from=("longitude", "latitude"),
    )

    _replace_children(
        conn,
        "program_access_need",
        "program_id",
        program_ids,
        PROGRAM_ACCESS_NEED_COLUMNS,
        needs,
    )

    _replace_children(
        conn,
        "program_sport",
        "program_id",
        program_ids,
        PROGRAM_SPORT_COLUMNS,
        sports,
    )

    quarantined = write_quarantine(
        conn,
        load_run_id,
        source_id,
        result.quarantine,
        sink=sink,
    )

    rate = check_rejection_rate(
        source_id,
        loaded,
        quarantined,
    )

    return LoadOutcome(
        load_run_id=load_run_id,
        source_id=source_id,
        rows_read=rows_read,
        rows_loaded=loaded,
        rows_quarantined=quarantined,
        quarantine_rate_pct=rate,
        outside_scope=len(rejected),
    )
