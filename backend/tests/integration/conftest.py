"""A real PostGIS database for the tests that need one.

WHY THIS DIRECTORY EXISTS
    Every other backend test runs against the in-memory FakeRepository, so the
    SQL in repositories/postgres.py was executed by nothing. That is how the
    API came to resolve event sports through a seven-entry dict while the
    reviewed eighty-four-row crosswalk sat unused in the database, with the
    whole suite green.

    These tests apply the migrations to a throwaway database and run the real
    repository against them. They are skipped unless TEST_DATABASE_URL is set,
    so CI without a database stays green and nobody is blocked.

RUNNING THEM

    docker run -d --name sportable-test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=sportable -p 55432:5432 postgis/postgis:16-3.4

    TEST_DATABASE_URL=postgresql://postgres:test@127.0.0.1:55432/sportable \\
        uv run pytest tests/integration

THE DATABASE IS REBUILT, NOT REUSED
    Every migration is applied to a fresh schema on each session. Point
    TEST_DATABASE_URL at a disposable database: this drops the public schema.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SQL_DIR = REPO_ROOT / "data" / "sql"
SEED = Path(__file__).parent / "seed_crosswalk.sql"

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Two marks in one: `integration` is the repository's existing convention, so
# `pytest -m "not integration"` excludes these the way it already excludes the
# data suite's; the skipif is what keeps a plain `pytest` run green on a laptop
# with no container.
requires_db = pytest.mark.integration(
    pytest.mark.skipif(
        not TEST_DATABASE_URL,
        reason="TEST_DATABASE_URL is not set; see tests/integration/conftest.py",
    )
)


def migrations() -> list[Path]:
    """The numbered migrations, in order. schema_current.sql is a reference
    dump of 001 to 007 and is deliberately not applied."""
    return sorted(p for p in SQL_DIR.glob("[0-9][0-9][0-9]_*.sql"))


@pytest.fixture(scope="session")
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def seeded_database(database_url: str) -> str:
    """A database with every migration applied and the seed loaded."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")

    for path in migrations():
        sql = path.read_text(encoding="utf-8")
        with psycopg.connect(database_url, autocommit=True) as conn:
            try:
                conn.execute(sql)
            except psycopg.Error as error:
                pytest.fail(f"{path.name} failed to apply: {error}")

    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(SEED.read_text(encoding="utf-8"))

    return database_url


@pytest.fixture(scope="session")
def repo(seeded_database: str):
    """The real repository, pointed at the seeded database.

    Setting DATABASE_URL is not enough. Settings are read through an
    lru_cache and the connection pool is a module global, so by the time these
    tests run in a full-suite run both have already been built without a
    database -- which fails as a 503, not as a connection error. Clear each.
    """
    from app.core import db
    from app.core.config import get_settings
    from app.repositories.postgres import PostgresVenueRepository

    os.environ["DATABASE_URL"] = seeded_database
    get_settings.cache_clear()

    if db._pool is not None:
        db._pool.close()
        db._pool = None

    return PostgresVenueRepository()
