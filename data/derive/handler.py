#!/usr/bin/env python3
"""Lambda entry point for stage 3: derive statuses, refresh the read model,
then (Iteration 3) chunk and embed DS-09 programme descriptions.

Event:
    {"load_run_id": 12}          status + read model, then RAG   (loader's call)
    {"rag_only": true}           RAG only, for a backfill or rebuild
    {"skip_rag": true}           status only
    {"force_rag": true}          RAG may delete a large share of the index
"""Lambda entry point for stage 3: derive statuses and refresh the read model.

    data/derive/handler.py

INVOKED BY THE LOADER, NOT BY S3 AND NOT BY A SCHEDULE
    The spatial join that decides a venue's toilet status depends on every
    amenity source having landed. Running it inside the loader would compute a
    status from a half-loaded amenity table and then compute it again,
    differently, when the next source arrived. Running it on a schedule would
    mean guessing how long the loads take.

    The loader invokes this asynchronously once per event, after the transaction
    that loaded the data has committed. Asynchronously because the loader has
    nothing to do with the answer and should not hold a Lambda open for the
    minutes a full derive takes.

NO PANDAS HERE
    status_builder does its work in PostGIS — nearest-neighbour searches against
    a GiST index, not dataframes in Python. That is why this package is a tenth
    the size of the loader's and why it needs nothing but psycopg.

THE DS-09 PLACE STAGE RUNS LAST, AND RUNS EVERY TIME
    venue_match decides which DS-09 places are a government venue, and
    place_geography puts a suburb and a postcode on each of them. Both run after
    the statuses, on every invocation, not only after a DS-09 load: a DS-01 load
    adds venues, and a place that matched nothing last week can match one of
    them today. Both are cheap when there is nothing new, because each looks
    only at the rows still undecided.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from typing import Any

import boto3
import psycopg
from psycopg.rows import dict_row

from derive import chunk_index, status_builder
from derive.embedder import DEFAULT_MODEL_ID, TitanEmbedder
from derive import run

LOG = logging.getLogger("sportable.derive")
LOG.setLevel(logging.INFO)

SSM_DB_URL_PARAM = os.environ["SSM_DB_URL_PARAM"]
EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_MODEL_ID)
# Passed in by Terraform, read from SSM on the CI runner at apply time. NOT
# read from SSM here: this function has no route to the SSM API from its
# private subnet, and the call hangs rather than failing. Same trade, and the
# same reasoning, as the API's DATABASE_URL — see T5-config-observability.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# The fallback for a hand-run from a laptop or the bastion, where there IS a
# route to SSM. Empty in the deployed function.
SSM_DB_URL_PARAM = os.environ.get("SSM_DB_URL_PARAM", "")

ssm = boto3.client("ssm")


def database_url() -> str:
    if DATABASE_URL:
        return DATABASE_URL

    if not SSM_DB_URL_PARAM:
        raise RuntimeError("Neither DATABASE_URL nor SSM_DB_URL_PARAM is set.")

    return str(ssm.get_parameter(Name=SSM_DB_URL_PARAM, WithDecryption=True)["Parameter"]["Value"])


def log(event: str, **fields: Any) -> None:
    LOG.info(json.dumps({"event": event, **fields}))


def latest_load_run(conn) -> int:
    """The most recent successful load run, for a manual invocation with no payload."""
    row = conn.execute(
        """
        SELECT load_run_id
          FROM load_run
         WHERE outcome = 'succeeded'
      ORDER BY load_run_id DESC
         LIMIT 1
        """
    ).fetchone()

    if row is None:
        raise RuntimeError("No successful load run recorded. Load DS-01 before deriving status.")

    return row["load_run_id"]


def derive_status(dsn: str, event: dict[str, Any]) -> dict[str, Any]:
    # One connection, one transaction: committed when this block exits cleanly.
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        load_run_id = event.get("load_run_id") or latest_load_run(conn)

        log("DERIVE_STARTED", load_run_id=load_run_id)

        outcome = status_builder.build(conn, load_run_id=load_run_id)

        log(
            "DERIVE_COMPLETED",
            load_run_id=load_run_id,
            venues=outcome.venues,
            status_rows=outcome.status_rows,
            chain_rows=outcome.chain_rows,
            by_kind=outcome.by_kind,
        )

        # Last, inside the same connection. The materialised views are what the
        # API serves; until this runs the site shows the previous load's data.
        status_builder.refresh_read_model(conn)

        log("READ_MODEL_REFRESHED", load_run_id=load_run_id)

    return {
        "load_run_id": load_run_id,
        "venues": outcome.venues,
        "status_rows": outcome.status_rows,
        "chain_rows": outcome.chain_rows,
    }


def build_rag_index(dsn: str, allow_large_delete: bool) -> dict[str, Any]:
    """Chunk and embed programme text on its OWN connection.

    Separate from derive_status on purpose: that transaction has already
    committed, and a Bedrock failure here must not be able to roll it back.
    """
    log("RAG_INDEX_STARTED", model=EMBEDDING_MODEL_ID)

    embedder = TitanEmbedder(model_id=EMBEDDING_MODEL_ID)

    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            outcome = chunk_index.build_index(conn, embedder, allow_large_delete=allow_large_delete)
    except Exception as error:
        # Error text only. Never log programme text.
        log("RAG_INDEX_FAILED", error_type=type(error).__name__, error=str(error))
        raise

    result = asdict(outcome)
    log("RAG_INDEX_COMPLETED", model=EMBEDDING_MODEL_ID, **result)

    return result


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    dsn = ssm.get_parameter(Name=SSM_DB_URL_PARAM, WithDecryption=True)["Parameter"]["Value"]

    result: dict[str, Any] = {}

    if not event.get("rag_only"):
        result.update(derive_status(dsn, event))

    if not event.get("skip_rag"):
        result["rag"] = build_rag_index(dsn, allow_large_delete=bool(event.get("force_rag")))

    return result
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        load_run_id = event.get("load_run_id") or latest_load_run(conn)

        return run.derive_all(conn, load_run_id=load_run_id, log=log)
