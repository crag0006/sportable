"""Tests for the stage 3 Lambda: derive/handler.py and what ships with it.

NO DATABASE AND NO NETWORK. The connection, the SSM client and the three derive
modules are all replaced; what is tested is the wiring between them.

WHY THE PACKAGING TEST IS HERE
    The DS-09 derive stage was written, tested and merged, and then did not run
    in staging for one reason only: build_lambda.sh copied status_builder.py and
    nothing else, so venue_match and place_geography were never in the zip. That
    is invisible in a unit test of either module and invisible in review of
    either file. It is only visible from the two read together, which is what
    the second test does.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

os.environ.setdefault("SSM_DB_URL_PARAM", "/test/db/url")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")

from derive import handler

DATA_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = DATA_ROOT / "scripts" / "build_lambda.sh"


class FakeCursor:
    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, *args: Any, **kwargs: Any) -> None:
        return None


class FakeConn:
    """Enough of a psycopg connection for the handler to run against."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor()

    def commit(self) -> None:
        self.calls.append("commit")


def install_fakes(monkeypatch, calls: list[str]) -> None:
    """Replace everything the handler reaches outside itself."""

    class FakeSsm:
        def get_parameter(self, **kwargs: Any) -> dict[str, Any]:
            return {"Parameter": {"Value": "postgresql://test/test"}}

    monkeypatch.setattr(handler, "ssm", FakeSsm())
    monkeypatch.setattr(handler.psycopg, "connect", lambda *a, **k: FakeConn(calls))

    monkeypatch.setattr(
        handler.status_builder,
        "build",
        lambda conn, load_run_id: (
            calls.append("status_build")
            or handler.status_builder.StatusOutcome(
                load_run_id=load_run_id,
                venues=10,
                status_rows=40,
                chain_rows=60,
                by_kind={},
            )
        ),
    )
    monkeypatch.setattr(
        handler.status_builder,
        "refresh_read_model",
        lambda conn: calls.append("refresh_read_model"),
    )


def test_the_ds09_place_stage_runs_after_the_status_stage(monkeypatch) -> None:
    """Both DS-09 derive steps must run, and run after the venue statuses.

    venue_match reads venue_amenity_status' table, and place_geography's read
    model counts venues, so deriving places before the statuses exist would
    publish a place list built from the previous run.
    """
    calls: list[str] = []
    install_fakes(monkeypatch, calls)

    monkeypatch.setattr(
        handler.venue_match,
        "match_places",
        lambda conn: calls.append("match_places") or {"strong": 120, "none": 30},
    )
    monkeypatch.setattr(
        handler.place_geography,
        "build",
        lambda conn: (
            calls.append("place_build")
            or handler.place_geography.GeographyOutcome(
                rows_derived=550,
                places=552,
                geocoded=552,
                attempted=552,
                suburb_derived=548,
                postcode_derived=548,
                pair_derived=548,
                pair_published=540,
                geocoded_without_pair=4,
                suburb_comparable=500,
                suburb_agreed=490,
                postcode_comparable=500,
                postcode_agreed=495,
            )
        ),
    )

    result = handler.handler({"load_run_id": 42}, None)

    assert calls.index("status_build") < calls.index("match_places")
    assert calls.index("refresh_read_model") < calls.index("match_places")
    assert calls.index("match_places") < calls.index("place_build")

    # The counts belong in the response: this is how the pipeline run reports
    # how many places found a venue, which is the number that decides whether
    # events show accessibility tiles.
    assert result["places_matched"] == {"strong": 120, "none": 30}
    assert result["places_geocoded"] == 550


def test_the_package_ships_every_derive_module_the_handler_imports() -> None:
    """build_lambda.sh must copy what derive/handler.py imports.

    Read as a pair, because a module imported but not packaged is an
    ImportError at cold start in the VPC, where nobody sees it until a load
    silently stops deriving.
    """
    # Every name on the line, not just the first: the import that started this
    # was `from derive import place_geography, status_builder, venue_match`,
    # and a regex that stops at the first name would have missed two of three.
    imported = {
        name.strip()
        for line in re.findall(r"^from derive import (.+)$", handler_source(), re.MULTILINE)
        for name in line.split(",")
    }
    assert imported, "expected derive/handler.py to import at least one derive module"

    packaged = BUILD_SCRIPT.read_text(encoding="utf-8")
    missing = [name for name in imported if f"{name}.py" not in packaged]

    assert not missing, f"imported by the handler but never copied into the zip: {missing}"


def handler_source() -> str:
    return (DATA_ROOT / "derive" / "handler.py").read_text(encoding="utf-8")
