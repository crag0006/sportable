#!/usr/bin/env python3
"""Lambda entry point for stage 3: derive statuses, refresh the read model,
then (Iteration 3) chunk and embed DS-09 programme descriptions.

Event:
    {"load_run_id": 12}          status + read model, then RAG   (loader's call)
    {"rag_only": true}           RAG only, for a backfill or rebuild
    {"skip_rag": true}           status only
    {"force_rag": true}          RAG may delete a large share of the index
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

LOG = logging.getLogger("sportable.derive")
LOG.setLevel(logging.INFO)

SSM_DB_URL_PARAM = os.environ["SSM_DB_URL_PARAM"]
EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_MODEL_ID)

ssm = boto3.client("ssm")


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
