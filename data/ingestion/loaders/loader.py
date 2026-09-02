"""
ingestion/loaders/loader.py

Handles writes into the serving database.

This is the only layer that talks directly to the database. The transformers
above it prepare the data without needing database access.

The loader handles three main things:

- Checking that records are inside the Greater Melbourne boundary.
- Writing records in an idempotent way so the pipeline can be rerun safely.
- Stopping the load if too many rows are quarantined.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import pandas as pd
import psycopg
from psycopg.rows import dict_row


LOG = logging.getLogger("sportable.loader")

# CRS used by the serving database.
SRID = 7844

# Stop the load if more than this percentage of in-scope rows are quarantined.
MAX_QUARANTINE_RATE_PCT = 15.0


class LoadAborted(RuntimeError):
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

    row = conn.execute(
        "SELECT count(*) AS n FROM lga WHERE in_greater_melbourne"
    ).fetchone()

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

        with cur.copy(
            "COPY _scope_check (idx, lon, lat) FROM STDIN"
        ) as copy:
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

        target_columns = [
            c for c in columns
            if c not in (lon_col, lat_col)
        ] + ["geom"]

        parts = [
            "%s"
            for c in columns
            if c not in (lon_col, lat_col)
        ]

        # Put longitude and latitude at the end because they are used
        # to create the geometry in SQL.
        reordered = []

        for r in rows:
            keep = [
                v
                for i, v in enumerate(r)
                if i not in (lon_i, lat_i)
            ]

            keep += [r[lon_i], r[lat_i]]
            reordered.append(keep)

        rows = reordered

        values_expression = ", ".join(
            parts
            + [f"ST_SetSRID(ST_MakePoint(%s, %s), {SRID})"]
        )

    updates = ", ".join(
        f"{c} = EXCLUDED.{c}"
        for c in target_columns
        if c not in key_columns
    )

    sql = f"""
        INSERT INTO {table} ({", ".join(target_columns)})
        VALUES ({values_expression})
        ON CONFLICT ({", ".join(key_columns)})
        DO UPDATE SET {updates}
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)

    return len(rows)


def write_quarantine(
    conn,
    load_run_id: int,
    source_id: str,
    frame: pd.DataFrame,
) -> int:
    """Store rejected rows in the quarantine table."""

    if frame.empty:
        return 0

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

    rate = round(
        100 * quarantined / total,
        2,
    )

    if rate > MAX_QUARANTINE_RATE_PCT:
        raise LoadAborted(
            f"{source_id} quarantined {quarantined:,} of {total:,} rows "
            f"({rate}%), above the {MAX_QUARANTINE_RATE_PCT}% threshold. "
            f"The load has been abandoned. Inspect the quarantine table "
            f"before rerunning; do not raise the threshold to make this pass."
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

            if isinstance(value, float) and pd.isna(value):
                value = None

            elif value is pd.NaT:
                value = None

            elif hasattr(value, "item") and not isinstance(
                value,
                (str, bytes),
            ):
                try:
                    value = value.item()
                except Exception:
                    pass

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

        sports = venue_sports[
            venue_sports["venue_id"].isin(kept["venue_id"])
        ]

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