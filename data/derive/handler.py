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

from derive import place_geography, status_builder, venue_match

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

        # Committed before the place stage so the statuses and the read model
        # are durable on their own. A DS-09 stage that fails is a failure worth
        # seeing, but it is not a reason to lose a venue derive that succeeded.
        conn.commit()

        matched = venue_match.match_places(conn)

        log("PLACES_MATCHED", load_run_id=load_run_id, by_basis=matched)

        # build() derives the suburb and postcode and refreshes
        # place_vocabulary, which is why that view is not in
        # status_builder.READ_MODEL_VIEWS: it is refreshed here, after the rows
        # it reads have been written, rather than before.
        geography = place_geography.build(conn)

        log(
            "PLACE_GEOGRAPHY_DERIVED",
            load_run_id=load_run_id,
            rows_derived=geography.rows_derived,
            places=geography.places,
            suburb_derived=geography.suburb_derived,
            postcode_derived=geography.postcode_derived,
        )

    return {
        "load_run_id": load_run_id,
        "venues": outcome.venues,
        "status_rows": outcome.status_rows,
        "chain_rows": outcome.chain_rows,
        "places_matched": matched,
        "places_geocoded": geography.rows_derived,
    }
