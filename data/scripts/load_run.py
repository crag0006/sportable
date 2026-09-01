#!/usr/bin/env python3
"""Run transform and load for one or more sources, against a live database.

    export DATABASE_URL=postgresql://...@localhost:5433/sportable
    uv run python scripts/load_run.py --seed-sources
    uv run python scripts/load_run.py DS-06 DS-01 DS-02 DS-04 --raw ./_raw

WHY THIS EXISTS
    The transformers and loaders were written as library functions and nothing
    called them together. The notebooks profile the raw files; they do not load.
    This is the missing orchestrator.

ORDER MATTERS AND IS ENFORCED
    `clip_to_scope` in the loader refuses to run while the `lga` table is empty:

        "The LGA boundary layer is empty, so scope cannot be decided.
         Load DS-06 before loading any source that needs clipping."

    So the order is: seed `source` (a foreign-key target for everything else),
    then DS-06 boundaries, then DS-01 venues, then the amenity sources.

WHERE IT RUNS
    From a laptop, through the bastion tunnel. It cannot run in CI: the database
    is in a private subnet with no route from the internet, by design — see
    docs/adr/ADR-002. Turning this into a Lambda inside the VPC is the way to
    automate it, and that same Lambda would solve database migrations too.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
import yaml
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.loaders import loader  # noqa: E402
from ingestion.transformers import ds01_sport_facilities as ds01  # noqa: E402
from ingestion.transformers import ds02_public_toilets as ds02  # noqa: E402
from ingestion.transformers import ds04_accessible_parking as ds04  # noqa: E402

# ------------------------------------------------------------------ scope
#
# THE ONE JUDGEMENT CALL IN THIS FILE, MADE EXPLICIT SO IT CAN BE ARGUED WITH.
#
# The `lga` column is named `in_greater_melbourne`, which suggests the 31-council
# ABS definition. Iteration 1 does not use that: DS-01's source card filters on
# "LGA Name equal to 'Melbourne City Council'" and DS-06's card records
# `records_in_target_area: 1`. So the shipped scope is ONE council.
#
# This matters more than it looks. Every other source is clipped against the
# union of the flagged polygons, so widening this silently changes what "in
# scope" means for toilets and parking as well as venues. Change it with
# --scope, deliberately, not by editing a default.
DEFAULT_SCOPE = {"melbourne"}

_COUNCIL_WORDS = re.compile(r"\b(city|shire|rural|borough|council|of|the)\b", flags=re.IGNORECASE)


def normalise_lga(name: Any) -> str | None:
    """Reduce an LGA name to a comparable key.

    The publishers disagree about form: DS-01 says "Melbourne City Council",
    the ABS shapefile says "Melbourne". Both must reduce to "melbourne", or the
    scope filter silently matches nothing and every venue is dropped.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    s = _COUNCIL_WORDS.sub(" ", str(name))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s or None


# ------------------------------------------------------------------ helpers
def connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set. See docs/runbooks/operations.md.")
    if "localhost" not in url and "127.0.0.1" not in url:
        print("  note: DATABASE_URL does not point at the tunnel; is that intended?")
    return psycopg.connect(url, row_factory=dict_row, autocommit=False, connect_timeout=10)


def latest_raw(raw_root: Path, prefix: str) -> tuple[Path, str, str]:
    """Return (path, dt_partition, object_key) for the newest object of a prefix."""
    days = sorted((raw_root / prefix).glob("dt=*"))
    if not days:
        sys.exit(f"No raw data for {prefix} under {raw_root}. Run fetch_run.py first.")
    day = days[-1]
    files = [p for p in day.iterdir() if p.is_file()]
    if not files:
        sys.exit(f"{day} is empty.")
    path = files[0]
    return path, day.name.removeprefix("dt="), f"{prefix}/{day.name}/{path.name}"


def sha_of(raw_root: Path, object_key: str) -> str:
    """The fetch step already recorded a SHA-256; reuse it rather than recompute."""
    import hashlib

    return hashlib.sha256((raw_root / object_key).read_bytes()).hexdigest()


# ------------------------------------------------------------------ source seed
def seed_sources(conn: psycopg.Connection) -> int:
    """Populate `source` from the YAML cards.

    `source` is the foreign-key target for `lga`, `load_run` and `venue`, so
    nothing loads until it has rows. Every column here maps directly from a
    field the Data team already wrote in sources/*.yaml — there is no judgement
    in this function, only transcription.
    """
    rows = []
    for card in sorted((ROOT / "sources").glob("DS-*.yaml")):
        d = yaml.safe_load(card.read_text())
        lic = d.get("licence", {}) or {}
        rows.append(
            (
                d["source_id"],
                d["name"],
                d["publisher"],
                lic.get("name", "unknown"),
                lic.get("url", ""),
                (lic.get("attribution_text") or d["name"]).strip(),
                (d.get("retrieval") or {}).get("landing_page"),
                (d.get("coverage") or {}).get("publisher_scope", "unknown"),
                d.get("publisher_last_updated"),
                bool(d.get("iteration_1", False)),
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO source (source_id, name, publisher, licence_name, licence_url,
                                attribution_text, landing_page, publisher_scope,
                                publisher_last_updated, iteration_1)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source_id) DO UPDATE SET
                name = EXCLUDED.name,
                publisher = EXCLUDED.publisher,
                licence_name = EXCLUDED.licence_name,
                licence_url = EXCLUDED.licence_url,
                attribution_text = EXCLUDED.attribution_text,
                landing_page = EXCLUDED.landing_page,
                publisher_scope = EXCLUDED.publisher_scope,
                publisher_last_updated = EXCLUDED.publisher_last_updated,
                iteration_1 = EXCLUDED.iteration_1
            """,
            rows,
        )
    conn.commit()
    print(f"  source: {len(rows)} rows")
    return len(rows)


# ------------------------------------------------------------------ DS-06
def load_boundaries(conn: psycopg.Connection, raw_root: Path, scope: set[str]) -> int:
    """Load the ASGS LGA layer and flag the councils that define our scope.

    Reads the zipped GDA2020 shapefile directly. Storage is EPSG:7844, which is
    what GDA2020 already is, so there is no reprojection and no 1.8 m offset —
    that is why the source card insists on the GDA2020 file rather than GDA94.
    """
    import geopandas as gpd

    path, _, _ = latest_raw(raw_root, "lga_boundaries")
    with zipfile.ZipFile(path) as z:
        shp = next(n for n in z.namelist() if n.endswith(".shp"))
    gdf = gpd.read_file(f"zip://{path}!{shp}")

    # STE_CODE21 == "2" is Victoria. Loading the nation would work but costs
    # 500-odd polygons of storage to answer a question about one state.
    vic = gdf[gdf["STE_CODE21"] == "2"].copy()
    vic["lga_name_normalised"] = vic["LGA_NAME25"].map(normalise_lga)
    vic["in_greater_melbourne"] = vic["lga_name_normalised"].isin(scope)

    if vic.crs is None or vic.crs.to_epsg() != 7844:
        vic = vic.to_crs(7844)

    flagged = int(vic["in_greater_melbourne"].sum())
    if flagged == 0:
        sys.exit(
            f"Scope {sorted(scope)} matched no LGA. Nothing downstream would load.\n"
            f"Available (first 12): {sorted(vic['lga_name_normalised'].dropna())[:12]}"
        )

    rows = [
        (
            r["LGA_CODE25"],
            r["LGA_NAME25"],
            r["lga_name_normalised"],
            bool(r["in_greater_melbourne"]),
            "DS-06",
            r["geometry"].wkb,
        )
        for _, r in vic.iterrows()
        if r["geometry"] is not None and r["lga_name_normalised"]
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO lga (lga_code, lga_name, lga_name_normalised,
                             in_greater_melbourne, source_id, geom)
            VALUES (%s,%s,%s,%s,%s, ST_Multi(ST_SetSRID(ST_GeomFromWKB(%s), 7844)))
            ON CONFLICT (lga_code) DO UPDATE SET
                lga_name = EXCLUDED.lga_name,
                lga_name_normalised = EXCLUDED.lga_name_normalised,
                in_greater_melbourne = EXCLUDED.in_greater_melbourne,
                geom = EXCLUDED.geom
            """,
            rows,
        )
    conn.commit()
    print(f"  lga: {len(rows)} Victorian councils, {flagged} in scope {sorted(scope)}")
    return len(rows)


# ------------------------------------------------------------------ DS-01/02/04
def run_source(conn: psycopg.Connection, source_id: str, raw_root: Path, scope: set[str]) -> None:
    prefix = {
        "DS-01": "sport_facilities",
        "DS-02": "public_toilets",
        "DS-04": "accessible_parking",
    }[source_id]
    path, dt, key = latest_raw(raw_root, prefix)
    run_id = loader.open_load_run(conn, source_id, dt, key, sha_of(raw_root, key))
    retrieved_at = datetime.now(UTC)

    if source_id == "DS-01":
        raw = pd.read_excel(path, sheet_name="wholeIFMD")
        result = ds01.transform(raw, scope, normalise_lga, run_id, retrieved_at)
        outcome = loader.load_venues(
            conn,
            run_id,
            source_id,
            result.venues,
            result.venue_sports,
            result.quarantine,
            int(result.stats.get("rows_read", len(raw))),
        )
    else:
        mod = ds02 if source_id == "DS-02" else ds04
        if path.suffix == ".csv":
            raw = pd.read_csv(path)
        else:
            # DS-04 is a KML. Its transform expects a GeoDataFrame with a
            # `geometry` column and raises without one, so parsing belongs here
            # rather than being left to the caller.
            import geopandas as gpd

            raw = gpd.read_file(path)
        result = mod.transform(raw, run_id, retrieved_at)
        # DS-02 reports "rows_read"; DS-04 reports "features_read" — it counts
        # KML features, not CSV rows. Reading only the first key silently
        # recorded 0 rows read for DS-04, which makes the quarantine rate and
        # the quality report meaningless for that source.
        rows_read = int(result.stats.get("rows_read") or result.stats.get("features_read") or 0)
        outcome = loader.load_amenities(
            conn, run_id, source_id, result.amenities, result.quarantine, rows_read
        )

    loader.close_load_run(
        conn,
        run_id,
        rows_read=outcome.rows_read,
        rows_loaded=outcome.rows_loaded,
        rows_quarantined=outcome.rows_quarantined,
        outcome="success",
        rows_outside_scope=getattr(outcome, "rows_outside_scope", 0),
    )
    conn.commit()
    print(
        f"  {source_id}: loaded {outcome.rows_loaded}, "
        f"quarantined {outcome.rows_quarantined}, run_id {run_id}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source_ids", nargs="*", help="DS-06 DS-01 DS-02 DS-04, in that order")
    p.add_argument("--raw", default=str(ROOT / "_raw"))
    p.add_argument("--seed-sources", action="store_true")
    p.add_argument(
        "--scope",
        nargs="*",
        default=sorted(DEFAULT_SCOPE),
        help="normalised LGA names flagged in_greater_melbourne",
    )
    a = p.parse_args()

    raw_root = Path(a.raw).resolve()
    scope = {normalise_lga(s) for s in a.scope} - {None}

    with connect() as conn:
        if a.seed_sources:
            seed_sources(conn)
        for sid in a.source_ids:
            if sid == "DS-06":
                load_boundaries(conn, raw_root, scope)
            else:
                run_source(conn, sid, raw_root, scope)


if __name__ == "__main__":
    main()
