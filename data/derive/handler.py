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
from typing import Any

import boto3
import psycopg
from psycopg.rows import dict_row

from derive import run

LOG = logging.getLogger("sportable.derive")
LOG.setLevel(logging.INFO)

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


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        load_run_id = event.get("load_run_id") or latest_load_run(conn)

        return run.derive_all(conn, load_run_id=load_run_id, log=log)
