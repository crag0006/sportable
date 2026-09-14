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
import io
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

from derive import status_builder  # noqa: E402
from ingestion.loaders import loader  # noqa: E402
from ingestion.transformers import ds01_sport_facilities as ds01  # noqa: E402
from ingestion.transformers import ds02_public_toilets as ds02  # noqa: E402
from ingestion.transformers import ds03_ptv_gtfs as ds03  # noqa: E402
from ingestion.transformers import ds04_accessible_parking as ds04  # noqa: E402
from ingestion.transformers import ds08_postal_areas as ds08  # noqa: E402

# ------------------------------------------------------------------ scope
#
# THE ONE JUDGEMENT CALL IN THIS FILE, MADE EXPLICIT SO IT CAN BE ARGUED WITH.
#
# Scope is the whole of Victoria. An EMPTY set means every Victorian council in
# the DS-06 layer, which is why the default is empty rather than a list of
# eighty names: a list would go stale the next time the ABS renames a council,
# and it would go stale silently, by quietly dropping that council's venues.
#
# The `lga` column is still named `in_greater_melbourne`. That name is now a
# misnomer and is kept deliberately: renaming it would change the read model,
# the API and the frontend for no behavioural gain. Nothing reads the name; the
# flag simply means "in scope".
#
# This matters more than it looks. Every other source is clipped against the
# union of the flagged polygons, so narrowing this silently changes what "in
# scope" means for toilets and parking as well as venues. Narrow it with
# --scope, deliberately, not by editing this default.
#
# One honest limitation of the wider scope: DS-04 accessible parking is
# published by the City of Melbourne for its own area only. Venues elsewhere in
# Victoria therefore carry no parking record at all, and the product shows that
# as "no published information" rather than as an absence of parking.
DEFAULT_SCOPE: set[str] = set()

# Every function here receives the connection from connect(), which sets
# row_factory=dict_row. Naming the parameterised type once keeps the signatures
# honest: a bare psycopg.Connection means Connection[tuple[Any, ...]], and then
# row["id"] is a type error even though it works perfectly at runtime.
DictConnection = psycopg.Connection[dict[str, Any]]


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
def connect() -> DictConnection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set. See docs/runbooks/operations.md.")
    if "localhost" not in url and "127.0.0.1" not in url:
        print("  note: DATABASE_URL does not point at the tunnel; is that intended?")
    return psycopg.connect(url, row_factory=dict_row, autocommit=False, connect_timeout=10)


def scope_from_database(conn: DictConnection) -> set[str]:
    """The in-scope LGA names, read from the table rather than from a constant.

    The `lga` table is the single definition of scope. Reading it here rather
    than threading --scope through means DS-01 is filtered against what was
    actually flagged when DS-06 was loaded, which may have been a different run
    on a different day.

    This matters because ds01.transform DROPS rows whose LGA is not in the set —
    it does not quarantine them. An empty set silently produces an empty load,
    and an empty load looks exactly like a source that published nothing.
    """
    rows = conn.execute("SELECT lga_name_normalised FROM lga WHERE in_greater_melbourne").fetchall()

    scope = {row["lga_name_normalised"] for row in rows} - {None}

    if not scope:
        sys.exit(
            "No LGA is flagged in scope, so every venue would be dropped.\n"
            "Load DS-06 first: uv run python scripts/load_run.py DS-06"
        )

    return scope


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
def seed_sources(conn: DictConnection) -> int:
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
def load_boundaries(conn: DictConnection, raw_root: Path, scope: set[str]) -> int:
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

    # An empty scope flags every Victorian council. See DEFAULT_SCOPE: the
    # default is the whole state, and --scope narrows it.
    if scope:
        vic["in_greater_melbourne"] = vic["lga_name_normalised"].isin(scope)
    else:
        vic["in_greater_melbourne"] = True

    if vic.crs is None or vic.crs.to_epsg() != 7844:
        vic = vic.to_crs(7844)

    flagged = int(vic["in_greater_melbourne"].sum())
    if flagged == 0:
        scope_text = sorted(scope) if scope else "all Victoria"
        sys.exit(
            f"Scope {scope_text} matched no LGA. Nothing downstream would load.\n"
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
    scope_text = sorted(scope) if scope else "all Victoria"
    print(f"  lga: {len(rows)} Victorian councils, {flagged} in scope ({scope_text})")
    return len(rows)


# ------------------------------------------------------------------ DS-07
def load_suburbs(conn: DictConnection, raw_root: Path) -> int:
    """Load the ASGS Suburbs and Localities layer.

    Inline rather than a transformer, for the same reason DS-06 is: the work is
    read a shapefile, keep Victoria, write four columns. There is no column
    contract to enforce and no quarantine decision to make, so a transformer
    module would be a file that only moved code somewhere else.

    Unlike DS-06 this layer carries no scope flag. Suburbs are how the search
    box resolves a typed place name, and a suburb outside scope still has to
    resolve — the API answers "this area is not covered" rather than returning
    nothing, which AC1.1.4 requires.
    """
    import geopandas as gpd

    path, _, _ = latest_raw(raw_root, "suburb_boundaries")

    with zipfile.ZipFile(path) as archive:
        shp = next(n for n in archive.namelist() if n.endswith(".shp"))

    gdf = gpd.read_file(f"zip://{path}!{shp}")

    vic = gdf[gdf["STE_CODE21"] == "2"].copy()

    if vic.crs is None or vic.crs.to_epsg() != 7844:
        vic = vic.to_crs(7844)

    rows = [
        (
            r["SAL_CODE21"],
            r["SAL_NAME21"],
            "DS-07",
            r["geometry"].wkb,
        )
        for _, r in vic.iterrows()
        if r["geometry"] is not None and r["SAL_NAME21"]
    ]

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO suburb (suburb_code, suburb_name, source_id, geom)
            VALUES (%s,%s,%s, ST_Multi(ST_SetSRID(ST_GeomFromWKB(%s), 7844)))
            ON CONFLICT (suburb_code) DO UPDATE SET
                suburb_name = EXCLUDED.suburb_name,
                geom = EXCLUDED.geom
            """,
            rows,
        )

    conn.commit()
    print(f"  suburb: {len(rows)} Victorian suburbs and localities")
    return len(rows)


# ------------------------------------------------------------------ DS-03
#
# The PTV archive is nested: gtfs.zip holds one numbered directory per mode,
# each with its own google_transit.zip, each with its own stops.txt. The
# transformer takes ONE frame with mode_id and mode already attached, because
# the key is (mode_id, stop_id): 965 stop_id values repeat across feeds, and
# parent_station references are only unique inside a single mode feed.
PTV_MODES = {
    "1": "Regional train",
    "2": "Metropolitan train",
    "3": "Metropolitan tram",
    "4": "Metropolitan bus",
    "5": "Regional coach",
    "6": "Regional bus",
    "7": "TeleBus",
    "8": "Night bus",
    "10": "Interstate train",
    "11": "SkyBus",
}


def read_gtfs_stops(path: Path, modes: set[str] | None = None) -> pd.DataFrame:
    """Concatenate stops.txt from every mode feed inside the outer archive.

    `modes` narrows to a set of mode directory numbers. None reads all of them.
    Narrowing is a real option rather than a convenience: the metropolitan bus
    feed alone is larger than every other mode combined, and a rail-only run is
    the fast way to check the transform after a change.
    """
    frames: list[pd.DataFrame] = []

    with zipfile.ZipFile(path) as outer:
        inner_names = sorted(
            (n for n in outer.namelist() if n.lower().endswith("google_transit.zip")),
            key=lambda n: int(n.split("/")[0]) if n.split("/")[0].isdigit() else 99,
        )

        if not inner_names:
            sys.exit(f"No per-mode google_transit.zip inside {path}. Is this the PTV archive?")

        for name in inner_names:
            mode_id = name.split("/")[0]

            if modes and mode_id not in modes:
                continue

            # Decompress the inner archive once. Reading members straight from
            # the outer zip re-decompresses the whole thing on every call.
            with outer.open(name) as handle:
                inner = zipfile.ZipFile(io.BytesIO(handle.read()))

            with inner.open("stops.txt") as stops_file:
                frame = pd.read_csv(stops_file, dtype=str, low_memory=False)

            frame["mode_id"] = mode_id
            frame["mode"] = PTV_MODES.get(mode_id, f"Unknown mode {mode_id}")
            frames.append(frame)

            print(f"    mode {mode_id} {frame['mode'].iloc[0]:<22} {len(frame):,} stops")

    if not frames:
        sys.exit("No mode feeds matched. Check --gtfs-modes.")

    return pd.concat(frames, ignore_index=True)


# ------------------------------------------------------------------ DS-01/02/04
def run_source(
    conn: DictConnection,
    source_id: str,
    raw_root: Path,
    scope: set[str],
    gtfs_modes: set[str] | None = None,
) -> None:
    prefix = {
        "DS-01": "sport_facilities",
        "DS-02": "public_toilets",
        "DS-03": "ptv_gtfs",
        "DS-04": "accessible_parking",
        "DS-08": "postal_areas",
    }[source_id]
    path, dt, key = latest_raw(raw_root, prefix)
    run_id = loader.open_load_run(conn, source_id, dt, key, sha_of(raw_root, key))
    retrieved_at = datetime.now(UTC)

    if source_id == "DS-01":
        raw = pd.read_excel(path, sheet_name="wholeIFMD")
        # A separate name per branch. Each transformer defines its own
        # TransformResult with different fields, so one shared variable is
        # narrowed to whichever type was assigned first and .amenities or
        # .postal_areas then fails to type-check.
        venue_result = ds01.transform(raw, scope, normalise_lga, run_id, retrieved_at)
        outcome = loader.load_venues(
            conn,
            run_id,
            source_id,
            venue_result.venues,
            venue_result.venue_sports,
            venue_result.quarantine,
            int(venue_result.stats.get("rows_read", len(raw))),
        )
    elif source_id == "DS-08":
        import geopandas as gpd

        with zipfile.ZipFile(path) as archive:
            shp = next(n for n in archive.namelist() if n.endswith(".shp"))

        raw = gpd.read_file(f"zip://{path}!{shp}")
        postal_result = ds08.transform(raw, run_id, retrieved_at)
        outcome = loader.load_postal_areas(
            conn,
            run_id,
            source_id,
            postal_result.postal_areas,
            postal_result.quarantine,
            int(postal_result.stats.get("features_read", len(raw))),
        )

    elif source_id == "DS-03":
        raw = read_gtfs_stops(path, gtfs_modes)
        transit_result = ds03.transform(raw, run_id, retrieved_at)
        outcome = loader.load_amenities(
            conn,
            run_id,
            source_id,
            transit_result.amenities,
            transit_result.quarantine,
            int(transit_result.stats.get("rows_read", len(raw))),
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
        amenity_result = mod.transform(raw, run_id, retrieved_at)
        # DS-02 reports "rows_read"; DS-04 reports "features_read" — it counts
        # KML features, not CSV rows. Reading only the first key silently
        # recorded 0 rows read for DS-04, which makes the quarantine rate and
        # the quality report meaningless for that source.
        rows_read = int(
            amenity_result.stats.get("rows_read") or amenity_result.stats.get("features_read") or 0
        )
        outcome = loader.load_amenities(
            conn,
            run_id,
            source_id,
            amenity_result.amenities,
            amenity_result.quarantine,
            rows_read,
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


def derive_status(conn: DictConnection) -> None:
    """Build venue_amenity_status and venue_access_chain from what is loaded.

    This is the step that turns loaded rows into what the product actually
    serves. Without it every venue reports "state": "none" for every facility —
    the amenities are in the database but nothing has decided which venue each
    one belongs to, or how far away it is.

    Like the loaders, `status_builder.build` had no caller.
    """
    row = conn.execute("SELECT max(load_run_id) AS id FROM load_run").fetchone()
    if not row or row["id"] is None:
        sys.exit("No load runs; nothing to derive from.")
    outcome = status_builder.build(conn, row["id"])
    conn.commit()
    print(
        f"  derived: {outcome.status_rows} status rows, "
        f"{outcome.chain_rows} chain rows, across {outcome.venues} venues"
    )
    for kind, counts in outcome.by_kind.items():
        print(f"    {kind:<26} {counts}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "source_ids",
        nargs="*",
        help="DS-06 DS-07 DS-08 DS-01 DS-02 DS-03 DS-04, in that order",
    )
    p.add_argument("--raw", default=str(ROOT / "_raw"))
    p.add_argument("--seed-sources", action="store_true")
    p.add_argument(
        "--derive",
        action="store_true",
        help="build venue_amenity_status and venue_access_chain after loading",
    )
    p.add_argument(
        "--scope",
        nargs="*",
        default=sorted(DEFAULT_SCOPE),
        help=(
            "normalised LGA names to flag as in scope. Omit for the whole of "
            "Victoria, which is the default."
        ),
    )
    p.add_argument(
        "--gtfs-modes",
        nargs="*",
        help=(
            "DS-03 only: mode directory numbers to read, e.g. 1 2 3 for rail and "
            "tram. Omit to read every mode."
        ),
    )
    a = p.parse_args()

    raw_root = Path(a.raw).resolve()
    # Subtracting {None} removes the value but not the type: mypy still sees
    # set[str | None]. Filtering in the comprehension narrows it properly.
    requested = {key for key in (normalise_lga(s) for s in a.scope) if key is not None}

    with connect() as conn:
        if a.seed_sources:
            seed_sources(conn)
        for sid in a.source_ids:
            if sid == "DS-06":
                # DS-06 SETS the flag, so it takes --scope directly. Empty means
                # every Victorian council.
                load_boundaries(conn, raw_root, requested)
            elif sid == "DS-07":
                load_suburbs(conn, raw_root)
            else:
                # Everything else READS the flag. Going through the database
                # keeps one definition of scope, and means a load run cannot
                # disagree with the boundaries already in the table.
                run_source(
                    conn,
                    sid,
                    raw_root,
                    scope_from_database(conn),
                    set(a.gtfs_modes) if a.gtfs_modes else None,
                )
        if a.derive:
            derive_status(conn)


if __name__ == "__main__":
    main()
