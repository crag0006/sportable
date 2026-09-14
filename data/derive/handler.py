#!/usr/bin/env python3
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
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
import psycopg
from psycopg.rows import dict_row

from derive import status_builder

LOG = logging.getLogger("sportable.derive")
LOG.setLevel(logging.INFO)

SSM_DB_URL_PARAM = os.environ["SSM_DB_URL_PARAM"]

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


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    dsn = ssm.get_parameter(Name=SSM_DB_URL_PARAM, WithDecryption=True)["Parameter"]["Value"]

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

        # Last, and inside the same connection. The materialised views are what
        # the API actually serves; until this runs, the site shows the previous
        # load's data no matter how much new data is in the base tables. The
        # refresh is concurrent so the site does not go blank while it runs.
        status_builder.refresh_read_model(conn)

        log("READ_MODEL_REFRESHED", load_run_id=load_run_id)

    return {
        "load_run_id": load_run_id,
        "venues": outcome.venues,
        "status_rows": outcome.status_rows,
        "chain_rows": outcome.chain_rows,
    }
