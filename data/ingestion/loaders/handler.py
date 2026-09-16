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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

import boto3
import pandas as pd
import psycopg
import yaml
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingestion.extractors import aaaplay
from ingestion.loaders import loader
from ingestion.transformers import ds01_sport_facilities as ds01
from ingestion.transformers import ds02_public_toilets as ds02
from ingestion.transformers import ds09_aaaplay as ds09

LOG = logging.getLogger("sportable.load")
LOG.setLevel(logging.INFO)

REGISTER_DIR = Path(os.environ.get("REGISTER_DIR", "/var/task/sources"))
RAW_BUCKET = os.environ["RAW_BUCKET"]
SSM_DB_URL_PARAM = os.environ["SSM_DB_URL_PARAM"]
DERIVE_FUNCTION = os.environ.get("DERIVE_FUNCTION", "")

# Rejected rows are written here BEFORE the rejection-rate check. An abort rolls
# the load transaction back, taking the quarantine TABLE rows with it, so on the
# one path where the evidence matters most the table is empty. S3 is outside the
# transaction. Unset means no sink and the table-only behaviour, which is what
# load_run.py does over the tunnel.
QUARANTINE_BUCKET = os.environ.get("QUARANTINE_BUCKET", "")

SUPPORTED = {"DS-01", "DS-02", "DS-09"}

s3 = boto3.client("s3")
ssm = boto3.client("ssm")
lam = boto3.client("lambda")


def quarantine_to_s3(*, load_run_id: int, source_id: str, frame: pd.DataFrame) -> str | None:
    """Write rejected rows to the quarantine bucket as newline-delimited JSON.

    NDJSON rather than a single array so a very large rejection set can be read
    with `aws s3 cp ... - | head`, which is what an operator does first.

    The key carries the load run id, so the objects from one aborted load group
    together and a rerun cannot overwrite the evidence from the run before it.
    """

    if not QUARANTINE_BUCKET:
        return None

    key = f"{source_id}/dt={datetime.now(UTC).date().isoformat()}/load_run_{load_run_id}.ndjson"
    body = "\n".join(
        json.dumps(
            {
                "load_run_id": load_run_id,
                "source_id": source_id,
                "natural_key": row.get("natural_key"),
                "reason": row["reason"],
                "detail": row.get("detail"),
                "payload": row.get("payload") or {},
            },
            default=str,
        )
        for _, row in frame.iterrows()
    )

    s3.put_object(
        Bucket=QUARANTINE_BUCKET,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/x-ndjson",
    )
    log(
        "QUARANTINE_WRITTEN", source_id=source_id, load_run_id=load_run_id, key=key, rows=len(frame)
    )
    return key


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
    rows = conn.execute("SELECT lga_name_normalised FROM lga WHERE in_greater_melbourne").fetchall()

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
    """Split '<prefix>/dt=<date>/<filename>' into its three parts.

    The key is decoded first. S3 event notifications URL-encode the object key,
    so the '=' of the partition arrives as '%3D' and the key in the event is not
    the key in the bucket. Decoding an already-decoded key is a no-op, so the
    CLI runner, which passes the key verbatim, is unaffected.
    """
    parts = unquote_plus(key).split("/")

    if len(parts) != 3 or not parts[1].startswith("dt="):
        raise ValueError(f"Unexpected raw key layout: {key}")

    return parts[0], parts[1].removeprefix("dt="), parts[2]


# ---------------------------------------------------------------- read


def read_payload(local: Path, fmt: str) -> pd.DataFrame | dict[str, Any]:
    if fmt == "csv":
        # low_memory=False: the toilet map export mixes types within a column
        # and chunked inference produces different dtypes for the same column
        # depending on where the chunk boundary falls.
        return pd.read_csv(local, low_memory=False)

    if fmt == "xlsx":
        return pd.read_excel(local)

    if fmt == "api":
        # One JSON document, unpacked into the four arguments the DS-09
        # transformer takes. The shape is defined in the extractor, so the
        # collector and the reader cannot drift apart.
        return aaaplay.split(local.read_bytes())

    raise ValueError(f"No reader for format {fmt!r}")


def tabular(raw: pd.DataFrame | dict[str, Any]) -> pd.DataFrame:
    """Narrow a payload to a DataFrame.

    read_payload returns a DataFrame for the file sources and a dict for DS-09,
    so every branch of run_load has to say which of the two it expects. A raise
    rather than a cast: if a source card's format and its source id ever
    disagree, a named error at the top of the branch is far easier to read than
    a KeyError three frames down inside a transformer.
    """
    if isinstance(raw, dict):
        raise TypeError(
            "Expected a tabular payload but received the DS-09 API document. "
            "Check the source card's retrieval.format against its source_id."
        )

    return raw


def document(raw: pd.DataFrame | dict[str, Any]) -> dict[str, Any]:
    """Narrow a payload to the collected DS-09 document. See tabular()."""
    if not isinstance(raw, dict):
        raise TypeError(
            "Expected the DS-09 API document but received a tabular payload. "
            "Check the source card's retrieval.format against its source_id."
        )

    return raw


def rows_read(raw: pd.DataFrame | dict[str, Any]) -> int:
    """How many source records a payload represents.

    For a DS-09 document that is the activity count, not the sum of all three
    post types. Facilities and organisations are dimensions the activities point
    at; counting them would inflate rows_read and quietly deflate the quarantine
    rate the loader's abort threshold is measured against.
    """
    if isinstance(raw, dict):
        return len(raw.get("activities") or [])

    return len(raw)


def sha256_of(local: Path) -> str:
    digest = hashlib.sha256()

    with local.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


# ---------------------------------------------------------------- load


def run_load(
    conn,
    source_id: str,
    raw: pd.DataFrame | dict[str, Any],
    dt: str,
    key: str,
    sha: str,
):
    load_run_id = loader.open_load_run(
        conn,
        source_id=source_id,
        dt_partition=dt,
        raw_object_key=key,
        raw_sha256=sha,
    )

    log("LOAD_RUN_OPENED", source_id=source_id, load_run_id=load_run_id, key=key)

    # Separate names per branch. ds01 and ds02 each define their own
    # TransformResult with different fields, so one shared variable would be
    # narrowed to whichever type was assigned first and .amenities would not
    # type-check.
    try:
        if source_id == "DS-01":
            venue_result = ds01.transform(
                tabular(raw),
                in_scope_lgas=scope_from_database(conn),
                normalise_lga=normalise_lga,
                load_run_id=load_run_id,
            )
            outcome = loader.load_venues(
                conn,
                sink=quarantine_to_s3,
                load_run_id=load_run_id,
                source_id=source_id,
                venues=venue_result.venues,
                venue_sports=venue_result.venue_sports,
                quarantine=venue_result.quarantine,
                rows_read=rows_read(raw),
            )

        elif source_id == "DS-09":
            # DS-09 is not part of the access chain. It writes to the program
            # tables only, and nothing it carries can produce a facility status,
            # so no derive step follows it. See the source card.
            collected = document(raw)
            program_result = ds09.transform(
                activities=collected["activities"],
                facilities=collected["facilities"],
                organisations=collected["organisations"],
                taxonomy_terms=collected["taxonomy_terms"],
                load_run_id=load_run_id,
                retrieved_at=dt,
            )
            outcome = loader.load_programs(
                conn,
                sink=quarantine_to_s3,
                load_run_id=load_run_id,
                source_id=source_id,
                result=program_result,
                rows_read=rows_read(raw),
            )

        else:
            amenity_result = ds02.transform(tabular(raw), load_run_id=load_run_id)
            outcome = loader.load_amenities(
                conn,
                sink=quarantine_to_s3,
                load_run_id=load_run_id,
                source_id=source_id,
                amenities=amenity_result.amenities,
                quarantine=amenity_result.quarantine,
                rows_read=rows_read(raw),
            )

    except loader.LoadAbortedError as error:
        # The loader aborts when the quarantine rate crosses its ceiling. That is
        # a deliberate stop, not a crash: a publisher schema change should leave
        # the previous good data in place rather than replace it with a mostly
        # empty table. Record it and re-raise so the invocation fails visibly.
        loader.close_load_run(
            conn,
            load_run_id=load_run_id,
            rows_read=rows_read(raw),
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


def handle_record(
    record: dict[str, Any],
    register: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    # Decoded here, at the edge, because everything below treats this as the
    # key in the bucket: it is downloaded with it and it is written to
    # load_run.raw_object_key as provenance. An event key is URL-encoded, so
    # 'dt=' arrives as 'dt%3D' and both of those uses would be wrong.
    key = unquote_plus(record["s3"]["object"]["key"])

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

    log("PAYLOAD_READ", source_id=source_id, key=key, rows=rows_read(raw), sha256=sha[:12])

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
