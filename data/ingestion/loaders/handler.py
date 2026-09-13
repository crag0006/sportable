#!/usr/bin/env python3
"""Lambda entry point for stage 2: transform a raw object and load it.

    data/ingestion/loaders/handler.py

TRIGGERED BY S3, NOT BY A SCHEDULE
    The fetch function answers a 304, or an unchanged SHA-256, by writing a
    manifest and NOT writing a payload. No payload means no ObjectCreated event
    means no load. A quiet week costs nothing and needs nobody to arrange for it
    to cost nothing.

WHY THIS EXISTS SEPARATELY FROM scripts/load_run.py
    load_run.py is an argparse CLI: it takes a list of source ids, reads from a
    local _raw directory and prints a summary for a human. None of that is a
    Lambda handler. This file is the same pipeline driven by an S3 event instead
    of a command line, and it deliberately calls the same transformer and loader
    functions so there is one implementation of the rules, not two.

SCOPE IS READ FROM THE DATABASE, NOT HARDCODED
    load_run.py carries DEFAULT_SCOPE = {"melbourne"} and a --scope flag. A
    Lambda has no command line, so a default here would be a scope decision
    frozen into code and invisible at runtime. Instead the in-scope LGA names
    are read from the lga table, which is the same list the loader clips
    against. Changing scope is then an UPDATE, not a deploy.

WHAT THIS FUNCTION DOES NOT HANDLE
    DS-04, DS-06, DS-07 and DS-08 transform GeoDataFrames and need geopandas,
    shapely, pyproj and fiona — comfortably over Lambda's 250 MB unzipped limit.
    They are loaded by hand through the bastion tunnel with load_run.py. That is
    a deliberate split, not an omission: those four are boundary and reference
    layers that the ABS republishes annually, so a weekly schedule would buy
    nothing. An unrecognised source id is logged and skipped, not failed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
import psycopg
import yaml
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingestion.loaders import loader  # noqa: E402
from ingestion.transformers import ds01_sport_facilities as ds01  # noqa: E402
from ingestion.transformers import ds02_public_toilets as ds02  # noqa: E402

LOG = logging.getLogger("sportable.load")
LOG.setLevel(logging.INFO)

REGISTER_DIR = Path(os.environ.get("REGISTER_DIR", "/var/task/sources"))
RAW_BUCKET = os.environ["RAW_BUCKET"]
QUARANTINE_BUCKET = os.environ.get("QUARANTINE_BUCKET", "")
SSM_DB_URL_PARAM = os.environ["SSM_DB_URL_PARAM"]
DERIVE_FUNCTION = os.environ.get("DERIVE_FUNCTION", "")

SUPPORTED = {"DS-01", "DS-02"}

s3 = boto3.client("s3")
ssm = boto3.client("ssm")
lam = boto3.client("lambda")


def log(event: str, **fields: Any) -> None:
    """One JSON object per line. The CloudWatch metric filters key off `event`."""
    LOG.info(json.dumps({"event": event, **fields}))


# ---------------------------------------------------------------- scope

# Kept character for character in step with load_run.normalise_lga. The two must
# agree: the publishers disagree about form — DS-01 says "Melbourne City
# Council", the ABS shapefile says "Melbourne" — and if the two implementations
# drift, the scope filter silently matches nothing and every venue is dropped as
# out of scope. A load that quarantines everything looks exactly like a load
# that worked on an empty file.
_COUNCIL_WORDS = re.compile(r"\b(city|shire|rural|borough|council|of|the)\b", flags=re.IGNORECASE)


def normalise_lga(name: Any) -> str | None:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None
    s = _COUNCIL_WORDS.sub(" ", str(name))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s or None


def scope_from_database(conn) -> set[str]:
    rows = conn.execute(
        "SELECT lga_name_normalised FROM lga WHERE in_greater_melbourne"
    ).fetchall()

    scope = {row["lga_name_normalised"] for row in rows} - {None}

    if not scope:
        raise RuntimeError(
            "No LGA is flagged in scope, so every row would be quarantined as "
            "out of scope. Load DS-06 before loading DS-01."
        )

    return scope


# ---------------------------------------------------------------- register


def load_register() -> dict[str, dict[str, Any]]:
    """Map raw_prefix -> source card. The prefix is the first path segment of the key."""
    register: dict[str, dict[str, Any]] = {}

    for path in sorted(REGISTER_DIR.glob("*.yaml")):
        card = yaml.safe_load(path.read_text(encoding="utf-8"))
        prefix = card.get("retrieval", {}).get("raw_prefix")

        if prefix:
            register[prefix] = card

    if not register:
        raise RuntimeError(
            f"No source cards under {REGISTER_DIR}. The build step must copy "
            "data/sources/*.yaml into the package as sources/."
        )

    return register


def parse_key(key: str) -> tuple[str, str, str]:
    """Split '<prefix>/dt=<date>/<filename>' into its three parts."""
    parts = key.split("/")

    if len(parts) != 3 or not parts[1].startswith("dt="):
        raise ValueError(f"Unexpected raw key layout: {key}")

    return parts[0], parts[1].removeprefix("dt="), parts[2]


# ---------------------------------------------------------------- read


def read_payload(local: Path, fmt: str) -> pd.DataFrame:
    if fmt == "csv":
        # low_memory=False: the toilet map export mixes types within a column
        # and chunked inference produces different dtypes for the same column
        # depending on where the chunk boundary falls.
        return pd.read_csv(local, low_memory=False)

    if fmt == "xlsx":
        return pd.read_excel(local)

    raise ValueError(f"No reader for format {fmt!r}")


def sha256_of(local: Path) -> str:
    digest = hashlib.sha256()

    with local.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


# ---------------------------------------------------------------- load


def run_load(conn, source_id: str, raw: pd.DataFrame, dt: str, key: str, sha: str):
    load_run_id = loader.open_load_run(
        conn,
        source_id=source_id,
        dt_partition=dt,
        raw_object_key=key,
        raw_sha256=sha,
    )

    log("LOAD_RUN_OPENED", source_id=source_id, load_run_id=load_run_id, key=key)

    try:
        if source_id == "DS-01":
            result = ds01.transform(
                raw,
                in_scope_lgas=scope_from_database(conn),
                normalise_lga=normalise_lga,
                load_run_id=load_run_id,
            )
            outcome = loader.load_venues(
                conn,
                load_run_id=load_run_id,
                source_id=source_id,
                venues=result.venues,
                venue_sports=result.venue_sports,
                quarantine=result.quarantine,
                rows_read=len(raw),
            )

        else:
            result = ds02.transform(raw, load_run_id=load_run_id)
            outcome = loader.load_amenities(
                conn,
                load_run_id=load_run_id,
                source_id=source_id,
                amenities=result.amenities,
                quarantine=result.quarantine,
                rows_read=len(raw),
            )

    except loader.LoadAborted as error:
        # The loader aborts when the quarantine rate crosses its ceiling. That is
        # a deliberate stop, not a crash: a publisher schema change should leave
        # the previous good data in place rather than replace it with a mostly
        # empty table. Record it and re-raise so the invocation fails visibly.
        loader.close_load_run(
            conn,
            load_run_id=load_run_id,
            rows_read=len(raw),
            rows_loaded=0,
            rows_quarantined=0,
            outcome="aborted",
        )
        log("LOAD_ABORTED", source_id=source_id, load_run_id=load_run_id, reason=str(error))
        raise

    loader.close_load_run(
        conn,
        load_run_id=load_run_id,
        rows_read=outcome.rows_read,
        rows_loaded=outcome.rows_loaded,
        rows_quarantined=outcome.rows_quarantined,
        outcome="succeeded",
        rows_outside_scope=outcome.outside_scope,
    )

    log(
        "LOAD_RUN_CLOSED",
        source_id=source_id,
        load_run_id=load_run_id,
        rows_read=outcome.rows_read,
        rows_loaded=outcome.rows_loaded,
        rows_quarantined=outcome.rows_quarantined,
        quarantine_rate_pct=round(outcome.quarantine_rate_pct, 2),
        outside_scope=outcome.outside_scope,
    )

    return outcome


# ---------------------------------------------------------------- handler


def handle_record(record: dict[str, Any], register: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = record["s3"]["object"]["key"]

    # Manifests are written on every run, including runs that landed nothing.
    # They are provenance, not payload, and there is no transformer for them.
    if key.startswith("_manifests/"):
        return None

    prefix, dt, filename = parse_key(key)
    card = register.get(prefix)

    if card is None:
        log("UNKNOWN_PREFIX", key=key, prefix=prefix)
        return None

    source_id = card["source_id"]

    if source_id not in SUPPORTED:
        # Not a failure. See the module docstring: the geospatial sources are
        # loaded by hand on publication.
        log("SOURCE_NOT_AUTOMATED", source_id=source_id, key=key)
        return None

    local = Path("/tmp") / filename
    s3.download_file(RAW_BUCKET, key, str(local))

    sha = sha256_of(local)
    raw = read_payload(local, card["retrieval"]["format"])

    log("PAYLOAD_READ", source_id=source_id, key=key, rows=len(raw), sha256=sha[:12])

    dsn = ssm.get_parameter(Name=SSM_DB_URL_PARAM, WithDecryption=True)["Parameter"]["Value"]

    # The connection is a transaction. Everything below either commits together
    # or rolls back together, so a failure halfway through cannot leave the
    # venue table loaded and the load_run row saying it never finished.
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        outcome = run_load(conn, source_id, raw, dt, key, sha)

    local.unlink(missing_ok=True)

    return {
        "source_id": source_id,
        "load_run_id": outcome.load_run_id,
        "rows_loaded": outcome.rows_loaded,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    register = load_register()
    results: list[dict[str, Any]] = []

    for record in event.get("Records", []):
        outcome = handle_record(record, register)

        if outcome:
            results.append(outcome)

    # The derive step is invoked once per handler call, not once per record, and
    # only if something actually landed. It recomputes status for every venue,
    # so running it twice for two records in one event would do the same work
    # twice and produce the same answer.
    if results and DERIVE_FUNCTION:
        lam.invoke(
            FunctionName=DERIVE_FUNCTION,
            InvocationType="Event",
            Payload=json.dumps({"load_run_id": results[-1]["load_run_id"]}).encode(),
        )
        log("DERIVE_INVOKED", function=DERIVE_FUNCTION, load_run_id=results[-1]["load_run_id"])

    return {"loaded": results}
