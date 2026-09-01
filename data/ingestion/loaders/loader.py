"""
ingestion/loaders/loader.py

Idempotent writes into the serving store. This is the only layer that talks to
the database; the transformers above it are pure and know nothing about it.

Three things happen here that cannot happen in a pure transformer:

The spatial clip
    Scope is decided by the boundary layer, not by an LGA name and not by the
    bounding box in profile_lib. The transformers filter on name so they can be
    tested without geometry, and the loader then re-checks every row against
    the union of the 31 Greater Melbourne councils. Anything outside is
    quarantined as OUTSIDE_SCOPE rather than dropped, so the count is visible.

Idempotency
    Every write is an upsert keyed on the natural or derived primary key, so a
    rerun of the same partition produces the same table state rather than
    duplicate rows. The pipeline must be safe to replay, because it will be
    replayed the first time something downstream is wrong.

The rejection alarm
    A load whose quarantine rate exceeds the threshold stops rather than
    completing quietly. A pipeline that silently drops a fifth of its rows is
    worse than one that fails, because the failure is visible and the silence
    is not.
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

# The working CRS for the whole serving store. GDA2020 geographic, which is what
# the ABS boundary layers declare, so the reference data needs no reprojection
# and only incoming sources are transformed.
SRID = 7844

# A load that rejects more than this share of its in-scope rows stops. The DS-01
# baseline is 9.09 per cent, entirely coordinate-less facilities, so the
# threshold sits above that and below anything that would indicate a broken
# contract. Raising it to accommodate a bad load defeats its purpose.
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
    """Open a connection with dict rows. Commits on success, rolls back on error."""
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
    """Register a run and return its id.

    The raw object key and its SHA-256 are recorded before any row is written,
    so every loaded row can be traced back to the exact bytes it came from.
    """
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
        (rows_read, rows_loaded, rows_quarantined, rows_outside_scope, outcome, load_run_id),
    )


# Scope


def greater_melbourne_wkb(conn) -> bytes | None:
    """The union of the 31 Greater Melbourne councils, or None if not loaded."""
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
    """Split rows into in-scope and out-of-scope against the boundary layer.

    Returns (kept, rejected). The check runs in the database so it uses the same
    geometry and the same predicate the serving queries will use, rather than a
    second implementation that could disagree with it.
    """
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
        cur.execute("CREATE TEMP TABLE _scope_check (idx integer, lon double precision, lat double precision) ON COMMIT DROP")
        with cur.copy("COPY _scope_check (idx, lon, lat) FROM STDIN") as copy:
            for record in points:
                copy.write_row(record)
        cur.execute(
            f"""
            SELECT c.idx
              FROM _scope_check c
             WHERE EXISTS (
                   SELECT 1 FROM lga l
                    WHERE l.in_greater_melbourne
                      AND ST_Intersects(l.geom, ST_SetSRID(ST_MakePoint(c.lon, c.lat), {SRID}))
             )
            """
        )
        inside = {r["idx"] for r in cur.fetchall()}
        cur.execute("DROP TABLE IF EXISTS _scope_check")

    mask = frame.index.map(lambda i: int(i) in inside)
    return frame[mask], frame[~pd.Series(mask, index=frame.index)]


# Writes


def _upsert(
    conn,
    table: str,
    columns: Sequence[str],
    key_columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    geometry_from: tuple[str, str] | None = None,
) -> int:
    """Insert or update rows, keyed on key_columns.

    geometry_from names the longitude and latitude columns to build the geom
    from. The point is constructed in SQL rather than in Python so the SRID is
    applied by PostGIS and cannot be forgotten.
    """
    rows = list(rows)
    if not rows:
        return 0

    placeholders = ", ".join(["%s"] * len(columns))
    target_columns = list(columns)
    values_expression = placeholders

    if geometry_from:
        lon_col, lat_col = geometry_from
        lon_i, lat_i = columns.index(lon_col), columns.index(lat_col)
        target_columns = [c for c in columns if c not in (lon_col, lat_col)] + ["geom"]
        parts = [f"%s" for c in columns if c not in (lon_col, lat_col)]
        # Rebuild the tuple order to match: non-geometry columns, then the point.
        reordered = []
        for r in rows:
            keep = [v for i, v in enumerate(r) if i not in (lon_i, lat_i)]
            keep += [r[lon_i], r[lat_i]]
            reordered.append(keep)
        rows = reordered
        values_expression = ", ".join(parts + [f"ST_SetSRID(ST_MakePoint(%s, %s), {SRID})"])

    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in target_columns if c not in key_columns
    )
    sql = f"""
        INSERT INTO {table} ({", ".join(target_columns)})
        VALUES ({values_expression})
        ON CONFLICT ({", ".join(key_columns)}) DO UPDATE SET {updates}
    """

    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def write_quarantine(conn, load_run_id: int, source_id: str, frame: pd.DataFrame) -> int:
    """Persist rejected rows. Quarantine is evidence, not a bin."""
    if frame.empty:
        return 0
    records = [
        (
            load_run_id,
            source_id,
            row.get("natural_key"),
            row["reason"],
            row.get("detail"),
            json.dumps(row.get("payload") or {}, default=str),
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


def check_rejection_rate(source_id: str, loaded: int, quarantined: int) -> float:
    """Raise if the quarantine share exceeds the threshold."""
    # Out-of-scope rows are excluded by the caller before this is reached. The
    # denominator is rows that were in scope and therefore should have loaded.
    total = loaded + quarantined
    if total == 0:
        return 0.0
    rate = round(100 * quarantined / total, 2)
    if rate > MAX_QUARANTINE_RATE_PCT:
        raise LoadAborted(
            f"{source_id} quarantined {quarantined:,} of {total:,} rows ({rate}%), "
            f"above the {MAX_QUARANTINE_RATE_PCT}% threshold. The load has been "
            f"abandoned. Inspect the quarantine table before rerunning; do not "
            f"raise the threshold to make this pass."
        )
    return rate


# Source-specific loads

VENUE_COLUMNS = [
    "venue_id", "source_id", "load_run_id", "name", "full_address",
    "suburb_name", "postcode", "lga_name", "ownership", "purpose",
    "changeroom_description", "onsite_accessible_toilet",
    "onsite_accessible_parking", "retrieved_at", "longitude", "latitude",
]

AMENITY_COLUMNS = [
    "amenity_id", "source_id", "load_run_id", "kind", "name", "address",
    "key_required", "mlak_24h", "payment_required", "opening_hours",
    "access_note", "facility_note", "is_inside_venue", "key_is_derived",
    "changing_places", "byo_sling", "has_shower", "ambulant",
    "left_hand_transfer", "right_hand_transfer", "accessible_parking_on_site",
    "retrieved_at", "longitude", "latitude",
]


def _tuples(frame: pd.DataFrame, columns: Sequence[str]) -> list[tuple]:
    """Project a frame onto the target columns, filling absent ones with null."""
    out = []
    for _, row in frame.iterrows():
        record = []
        for c in columns:
            value = row.get(c)
            if isinstance(value, float) and pd.isna(value):
                value = None
            elif value is pd.NaT:
                value = None
            elif hasattr(value, "item") and not isinstance(value, (str, bytes)):
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
    """Clip, upsert and account for a DS-01 transform result."""

    kept, rejected = clip_to_scope(conn, venues)

    loaded = _upsert(
        conn, "venue", VENUE_COLUMNS, ["venue_id"],
        _tuples(kept, VENUE_COLUMNS), geometry_from=("longitude", "latitude"),
    )

    # Child rows are replaced wholesale for the venues in this batch, because a
    # sport removed by the publisher must disappear rather than linger from a
    # previous run. Deleting only for the loaded venue ids keeps the operation
    # scoped to what this run actually saw.
    if loaded and not venue_sports.empty:
        ids = tuple(kept["venue_id"].tolist())
        sports = venue_sports[venue_sports["venue_id"].isin(kept["venue_id"])]
        with conn.cursor() as cur:
            cur.execute("DELETE FROM venue_sport WHERE venue_id = ANY(%s)", (list(ids),))
            cur.executemany(
                """
                INSERT INTO venue_sport (venue_id, sport, court_count, surface_type)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (venue_id, sport, surface_type) DO NOTHING
                """,
                _tuples(sports, ["venue_id", "sport", "court_count", "surface_type"]),
            )

    quarantined = write_quarantine(conn, load_run_id, source_id, quarantine)
    rate = check_rejection_rate(source_id, loaded, quarantined)

    return LoadOutcome(
        load_run_id=load_run_id,
        source_id=source_id,
        rows_read=rows_read,
        rows_loaded=loaded,
        rows_quarantined=quarantined,
        quarantine_rate_pct=rate,
        outside_scope=len(rejected),
    )


def load_amenities(
    conn,
    load_run_id: int,
    source_id: str,
    amenities: pd.DataFrame,
    quarantine: pd.DataFrame,
    rows_read: int,
) -> LoadOutcome:
    """Clip, upsert and account for a DS-02 or DS-04 transform result."""

    kept, rejected = clip_to_scope(conn, amenities)

    loaded = _upsert(
        conn, "amenity", AMENITY_COLUMNS, ["amenity_id"],
        _tuples(kept, AMENITY_COLUMNS), geometry_from=("longitude", "latitude"),
    )

    quarantined = write_quarantine(conn, load_run_id, source_id, quarantine)
    rate = check_rejection_rate(source_id, loaded, quarantined)

    return LoadOutcome(
        load_run_id=load_run_id,
        source_id=source_id,
        rows_read=rows_read,
        rows_loaded=loaded,
        rows_quarantined=quarantined,
        quarantine_rate_pct=rate,
        outside_scope=len(rejected),
    )