"""The loader runs the derive stage itself.

NO DATABASE AND NO NETWORK.

It used to invoke the derive Lambda asynchronously. That call is to the AWS
control plane, and this function's subnet has an S3 gateway endpoint and no
other route out, so the invoke did not fail — it hung until the timeout, after
the load had already committed. Every S3-triggered load would have ended that
way even once the SSM problem was solved, and the derive would simply never
have run.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("RAW_BUCKET", "test-raw-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")

from ingestion.loaders import handler

HANDLER_SOURCE = (
    Path(__file__).resolve().parents[1] / "ingestion" / "loaders" / "handler.py"
).read_text(encoding="utf-8")


class FakeConn:
    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


def test_the_derive_stage_runs_after_a_load(monkeypatch) -> None:
    """One derive per handler call, and only when something landed."""
    seen: dict[str, Any] = {}

    monkeypatch.setattr(handler, "load_register", lambda: {})
    monkeypatch.setattr(handler, "DATABASE_URL", "postgresql://test/test")
    monkeypatch.setattr(handler.psycopg, "connect", lambda *a, **k: FakeConn())
    monkeypatch.setattr(
        handler,
        "handle_record",
        lambda record, register: {"source_id": "DS-09", "load_run_id": 99, "rows_loaded": 532},
    )
    monkeypatch.setattr(
        handler.run,
        "derive_all",
        lambda conn, load_run_id, venue_stages=True, log=None: (
            seen.update(load_run_id=load_run_id) or {"places_matched": {"strong": 2}}
        ),
    )

    result = handler.handler({"Records": [{"s3": {}}]}, None)

    assert seen["load_run_id"] == 99, "the derive stage must run after a load"
    assert result["derived"] == {"places_matched": {"strong": 2}}


def test_nothing_derives_when_nothing_loaded(monkeypatch) -> None:
    """A manifest-only event loads nothing. Deriving then would recompute every
    venue's status for no new data."""
    monkeypatch.setattr(handler, "load_register", lambda: {})
    monkeypatch.setattr(handler, "handle_record", lambda record, register: None)
    monkeypatch.setattr(
        handler.run,
        "derive_all",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("derive ran with nothing loaded")),
    )

    assert handler.handler({"Records": [{"s3": {}}]}, None) == {"loaded": []}


def test_the_derive_lambda_is_no_longer_invoked() -> None:
    """The control-plane call is gone, not merely unused."""
    assert "lam.invoke" not in HANDLER_SOURCE
    assert "DERIVE_FUNCTION" not in HANDLER_SOURCE


def test_the_database_url_is_read_from_the_environment_not_ssm(monkeypatch) -> None:
    """Same reachability problem as the invoke, one line earlier: this is where
    the staging load actually died, with a ConnectTimeoutError on the SSM
    endpoint after reading 532 rows."""

    class ExplodingSsm:
        def get_parameter(self, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("SSM must not be called when DATABASE_URL is set")

    monkeypatch.setattr(handler, "ssm", ExplodingSsm())
    monkeypatch.setattr(handler, "DATABASE_URL", "postgresql://from-env/db")

    assert handler.database_url() == "postgresql://from-env/db"


def test_ssm_is_still_the_fallback_for_a_hand_run(monkeypatch) -> None:
    """scripts/load_run.py runs this code over the bastion tunnel, where SSM is
    reachable."""

    class FakeSsm:
        def get_parameter(self, **kwargs: Any) -> dict[str, Any]:
            return {"Parameter": {"Value": "postgresql://from-ssm/db"}}

    monkeypatch.setattr(handler, "ssm", FakeSsm())
    monkeypatch.setattr(handler, "DATABASE_URL", "")
    monkeypatch.setattr(handler, "SSM_DB_URL_PARAM", "/sportable/staging/db/url")

    assert handler.database_url() == "postgresql://from-ssm/db"


def test_a_ds09_only_load_skips_the_venue_stages(monkeypatch) -> None:
    """Nothing DS-09 carries can change a venue's facility status.

    Rebuilding them would redo the whole spatial join for the same answer and
    stamp the rows with a load run that did not produce them. The place stage
    still has to run, which is the half that makes events usable.
    """
    seen: dict[str, Any] = {}

    monkeypatch.setattr(handler, "load_register", lambda: {})
    monkeypatch.setattr(handler, "DATABASE_URL", "postgresql://test/test")
    monkeypatch.setattr(handler.psycopg, "connect", lambda *a, **k: FakeConn())
    monkeypatch.setattr(
        handler,
        "handle_record",
        lambda record, register: {"source_id": "DS-09", "load_run_id": 99, "rows_loaded": 532},
    )
    monkeypatch.setattr(
        handler.run,
        "derive_all",
        lambda conn, load_run_id, venue_stages=True, log=None: (
            seen.update(venue_stages=venue_stages) or {}
        ),
    )

    handler.handler({"Records": [{"s3": {}}]}, None)

    assert seen["venue_stages"] is False


def test_a_venue_load_still_runs_every_stage(monkeypatch) -> None:
    """A DS-01 or DS-02 load changes venues and amenities, so the statuses and
    the read model must be rebuilt."""
    seen: dict[str, Any] = {}

    monkeypatch.setattr(handler, "load_register", lambda: {})
    monkeypatch.setattr(handler, "DATABASE_URL", "postgresql://test/test")
    monkeypatch.setattr(handler.psycopg, "connect", lambda *a, **k: FakeConn())
    monkeypatch.setattr(
        handler,
        "handle_record",
        lambda record, register: {"source_id": "DS-02", "load_run_id": 12, "rows_loaded": 3753},
    )
    monkeypatch.setattr(
        handler.run,
        "derive_all",
        lambda conn, load_run_id, venue_stages=True, log=None: (
            seen.update(venue_stages=venue_stages) or {}
        ),
    )

    handler.handler({"Records": [{"s3": {}}]}, None)

    assert seen["venue_stages"] is True
