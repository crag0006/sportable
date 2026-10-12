"""The RAG build step: chunk, embed, store, then rebuild the BM25 tables.

Shared by the two callers, so there is one implementation:

    derive/handler.py             manual or backfill invocation ({"rag_only": true})
    ingestion/loaders/handler.py  automatically, after a DS-09 load

It opens its OWN connection. The load and the derive statuses have already
committed by the time this runs, and a Bedrock failure here must not be able to
roll any of that back. Progress is committed batch by batch (see chunk_index),
so a run that ends early still leaves a usable, resumable index.

Never logs programme text. Error text only.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import psycopg
from psycopg.rows import dict_row

from derive import bm25_index, chunk_index
from derive.embedder import DEFAULT_MODEL_ID, TitanEmbedder

LOG = logging.getLogger("sportable.derive.rag")
LOG.setLevel(logging.INFO)

EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_MODEL_ID)


def log(event: str, **fields: Any) -> None:
    LOG.info(json.dumps({"event": event, **fields}))


def seconds_left(context: Any) -> Callable[[], float] | None:
    """Seconds remaining in this Lambda invocation, or None outside Lambda."""
    remaining = getattr(context, "get_remaining_time_in_millis", None)

    if remaining is None:
        return None

    return lambda: float(remaining()) / 1000.0


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def build_rag_index(
    dsn: str,
    *,
    allow_large_delete: bool = False,
    time_left: Callable[[], float] | None = None,
) -> dict[str, Any]:
    log("RAG_INDEX_STARTED", model=EMBEDDING_MODEL_ID)

    embedder = TitanEmbedder(model_id=EMBEDDING_MODEL_ID)

    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            outcome = chunk_index.build_index(
                conn,
                embedder,
                allow_large_delete=allow_large_delete,
                batch_size=_int_env("EMBED_BATCH_SIZE", chunk_index.DEFAULT_BATCH_SIZE),
                workers=_int_env("EMBED_WORKERS", chunk_index.DEFAULT_WORKERS),
                checkpoint=conn.commit,
                time_left=time_left,
            )
            # Reflects whatever is stored now, so it also runs after a partial
            # index. The with-block commits it.
            bm25 = bm25_index.rebuild(conn, EMBEDDING_MODEL_ID)
    except Exception as error:
        log("RAG_INDEX_FAILED", error_type=type(error).__name__, error=str(error))
        raise

    result = {**asdict(outcome), "bm25": bm25}
    log("RAG_INDEX_COMPLETED" if outcome.complete else "RAG_INDEX_INCOMPLETE", **result)

    return result
