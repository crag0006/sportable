"""The derive sequence, its two callers, and what ships with each.

NO DATABASE AND NO NETWORK. The connection and the three derive modules are
replaced; what is tested is the wiring between them.

WHY THE PACKAGING TEST IS HERE
    The DS-09 derive stage was written, tested and merged, and then did not run
    in staging for one reason only: build_lambda.sh copied status_builder.py and
    nothing else, so venue_match and place_geography were never in the zip. That
    is invisible in a unit test of either module and invisible in review of
    either file. It is only visible from the two read together.

    It now has to hold for TWO packages, because the loader runs the derive
    sequence itself rather than invoking the derive Lambda across a network path
    that does not exist from its subnet.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

os.environ.setdefault("SSM_DB_URL_PARAM", "/test/db/url")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-2")

from derive import handler, run

DATA_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = DATA_ROOT / "scripts" / "build_lambda.sh"
DERIVE_DIR = DATA_ROOT / "derive"

ENTRY_POINTS = {
    # package name in build_lambda.sh -> the handler that package runs
    "derive": DERIVE_DIR / "handler.py",
    "load": DATA_ROOT / "ingestion" / "loaders" / "handler.py",
}


class FakeCursor:
    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, *args: Any, **kwargs: Any) -> None:
        return None


class FakeConn:
    """Enough of a psycopg connection for the sequence to run against."""

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
    """Replace the three derive modules the sequence calls."""
    monkeypatch.setattr(
        run.status_builder,
        "build",
        lambda conn, load_run_id: (
            calls.append("status_build")
            or run.status_builder.StatusOutcome(
                load_run_id=load_run_id, venues=10, status_rows=40, chain_rows=60, by_kind={}
            )
        ),
    )
    monkeypatch.setattr(
        run.status_builder, "refresh_read_model", lambda conn: calls.append("refresh_read_model")
    )
    monkeypatch.setattr(
        run.venue_match,
        "match_places",
        lambda conn: calls.append("match_places") or {"strong": 120, "none": 30},
    )
    monkeypatch.setattr(
        run.place_geography,
        "build",
        lambda conn: (
            calls.append("place_build")
            or run.place_geography.GeographyOutcome(
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


def test_the_ds09_place_stage_runs_after_the_status_stage(monkeypatch) -> None:
    """Both DS-09 derive steps must run, and run after the venue statuses.

    venue_match reads the venue tables, and place_geography's read model counts
    venues, so deriving places first would publish a list built from the
    previous run.
    """
    calls: list[str] = []
    install_fakes(monkeypatch, calls)

    result = run.derive_all(FakeConn(calls), load_run_id=42)

    assert calls.index("status_build") < calls.index("match_places")
    assert calls.index("refresh_read_model") < calls.index("match_places")
    assert calls.index("match_places") < calls.index("place_build")

    # The statuses are committed before the place stage, so a DS-09 failure
    # cannot roll back a venue derive that succeeded.
    assert calls.index("commit") < calls.index("match_places")

    assert result["places_matched"] == {"strong": 120, "none": 30}
    assert result["places_geocoded"] == 550


def test_the_derive_lambda_runs_the_same_sequence(monkeypatch) -> None:
    """The Lambda is a thin wrapper: a connection, an id, and the sequence.

    It still exists for a backfill, and it must not grow a second copy of the
    order the loader uses.
    """
    seen: dict[str, Any] = {}

    monkeypatch.setattr(handler, "DATABASE_URL", "postgresql://test/test")
    monkeypatch.setattr(handler.psycopg, "connect", lambda *a, **k: FakeConn([]))
    monkeypatch.setattr(
        handler.run,
        "derive_all",
        lambda conn, load_run_id, log=None: seen.update(load_run_id=load_run_id) or {"ok": True},
    )

    assert handler.handler({"load_run_id": 7}, None) == {"ok": True}
    assert seen["load_run_id"] == 7


def test_the_database_url_is_read_from_the_environment_not_ssm(monkeypatch) -> None:
    """There is no route from these subnets to the SSM API.

    Terraform reads the parameter on the runner and passes the value in. A
    handler that calls SSM here does not fail, it hangs until the timeout,
    which is the failure this replaced.
    """

    class ExplodingSsm:
        def get_parameter(self, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("SSM must not be called when DATABASE_URL is set")

    monkeypatch.setattr(handler, "ssm", ExplodingSsm())
    monkeypatch.setattr(handler, "DATABASE_URL", "postgresql://from-env/db")

    assert handler.database_url() == "postgresql://from-env/db"


def test_ssm_is_still_the_fallback_for_a_hand_run(monkeypatch) -> None:
    """From a laptop or the bastion there IS a route, and load_run.py uses it."""

    class FakeSsm:
        def get_parameter(self, **kwargs: Any) -> dict[str, Any]:
            return {"Parameter": {"Value": "postgresql://from-ssm/db"}}

    monkeypatch.setattr(handler, "ssm", FakeSsm())
    monkeypatch.setattr(handler, "DATABASE_URL", "")
    monkeypatch.setattr(handler, "SSM_DB_URL_PARAM", "/sportable/staging/db/url")

    assert handler.database_url() == "postgresql://from-ssm/db"


def test_every_package_ships_the_derive_modules_its_handler_reaches() -> None:
    """build_lambda.sh against the imports, transitively, for both packages.

    Transitively because handler.py imports run, and run imports the three
    modules that do the work: a check that stopped at the handler's own import
    line would be satisfied by a package containing run.py alone, which fails
    at cold start one import deeper.
    """
    packaged = BUILD_SCRIPT.read_text(encoding="utf-8")

    for package, entry_point in ENTRY_POINTS.items():
        needed = _derive_closure(entry_point)
        assert needed, f"expected {entry_point.name} to reach at least one derive module"

        copied = set(re.findall(rf'derive/(\w+)\.py" "\$BUILD_DIR/{package}/derive/', packaged))
        missing = needed - copied

        assert not missing, f"the {package} package does not ship: {sorted(missing)}"


def _derive_closure(entry_point: Path) -> set[str]:
    """Every derive module reachable from this file, following imports."""
    found: set[str] = set()
    queue = [entry_point]

    while queue:
        source = queue.pop().read_text(encoding="utf-8")

        for line in re.findall(r"^from derive import (.+)$", source, re.MULTILINE):
            for name in (n.strip() for n in line.split(",")):
                if name in found:
                    continue
                found.add(name)
                module = DERIVE_DIR / f"{name}.py"
                if module.exists():
                    queue.append(module)

    return found
