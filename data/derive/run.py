#!/usr/bin/env python3
"""The derive sequence, in one place.

    data/derive/run.py

TWO CALLERS, ONE ORDER
    The loader runs this inline once a load has committed, and the derive
    Lambda runs it when invoked by hand for a backfill. The order matters --
    statuses, then the read model, then the DS-09 places -- and an order that
    lived in two handlers would eventually be two orders.

WHY THE LOADER RUNS IT INLINE RATHER THAN INVOKING THE DERIVE LAMBDA
    lambda:InvokeFunction is a call to the AWS control plane, and these
    functions sit in a private subnet with an S3 gateway endpoint and no other
    route out. The call does not fail, it hangs until the timeout. Reaching the
    Lambda API from in there needs an interface endpoint at roughly USD $7.30
    per month per AZ, which is the same trade the T5 runbook already refused
    for SSM. Calling the code directly costs nothing and removes a moving part:
    there is no second invocation to lose, retry or run out of order.

    The derive Lambda still exists, for a backfill or a manual re-derive.
"""

from __future__ import annotations

import logging
from typing import Any

from derive import place_geography, status_builder, venue_match

LOG = logging.getLogger("sportable.derive")


def derive_all(
    conn: Any,
    *,
    load_run_id: int,
    venue_stages: bool = True,
    log: Any = None,
) -> dict[str, Any]:
    """Statuses, read model, then places. Returns what each stage did.

    `venue_stages=False` runs the place stage alone. A DS-09 load writes to the
    program tables only: nothing it carries can change a venue's facility
    status, so rebuilding every status would redo the whole spatial join for no
    new answer and stamp the rows with a load run that did not produce them.
    The places still have to be matched and geocoded, which is why the stage
    below always runs.

    `log` is the caller's structured logger, so the lines land in whichever
    function's log group is being read. Defaults to this module's logger.
    """
    emit = log or (lambda event, **fields: LOG.info("%s %s", event, fields))

    emit("DERIVE_STARTED", load_run_id=load_run_id, venue_stages=venue_stages)

    outcome = None

    if venue_stages:
        outcome = status_builder.build(conn, load_run_id=load_run_id)

        emit(
            "DERIVE_COMPLETED",
            load_run_id=load_run_id,
            venues=outcome.venues,
            status_rows=outcome.status_rows,
            chain_rows=outcome.chain_rows,
            by_kind=outcome.by_kind,
        )

        # The materialised views are what the API actually serves; until this
        # runs, the site shows the previous load's data no matter how much new
        # data is in the base tables. Concurrent, so the site does not go blank.
        status_builder.refresh_read_model(conn)

        emit("READ_MODEL_REFRESHED", load_run_id=load_run_id)

    # Committed before the place stage so the statuses and the read model are
    # durable on their own. A DS-09 stage that fails is a failure worth seeing,
    # but it is not a reason to lose a venue derive that succeeded.
    conn.commit()

    matched = venue_match.match_places(conn)

    emit("PLACES_MATCHED", load_run_id=load_run_id, by_basis=matched)

    # build() derives the suburb and postcode and refreshes place_vocabulary,
    # which is why that view is not in status_builder.READ_MODEL_VIEWS: it is
    # refreshed here, after the rows it reads have been written.
    geography = place_geography.build(conn)

    emit(
        "PLACE_GEOGRAPHY_DERIVED",
        load_run_id=load_run_id,
        rows_derived=geography.rows_derived,
        places=geography.places,
        suburb_derived=geography.suburb_derived,
        postcode_derived=geography.postcode_derived,
    )

    return {
        "load_run_id": load_run_id,
        "venues": outcome.venues if outcome else None,
        "status_rows": outcome.status_rows if outcome else None,
        "chain_rows": outcome.chain_rows if outcome else None,
        "places_matched": matched,
        "places_geocoded": geography.rows_derived,
    }
