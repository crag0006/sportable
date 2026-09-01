"""Database access: one small psycopg connection pool, created lazily.

Why a pool and not a single module-level connection: FastAPI runs sync route
functions in a thread pool, so under uvicorn two requests can overlap, and a
psycopg connection must not be shared across threads mid-query. In Lambda a
container serves one invocation at a time, so the pool simply holds one warm
connection across invocations — the same cold-start saving a bare connection
would give, without the local-dev footgun.

The pool is opened on first use, not at import, so importing the app (tests,
``--help``, cold start before the first request) never touches the network.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from app.core.config import get_settings
from app.core.errors import ApiError

_pool: ConnectionPool[Connection[DictRow]] | None = None


def get_pool() -> ConnectionPool[Connection[DictRow]]:
    global _pool
    if _pool is None:
        url = get_settings().database_url
        if not url:
            raise ApiError(503, "database_unavailable", "DATABASE_URL is not configured.")
        _pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=3,
            open=True,
            kwargs={"row_factory": dict_row, "autocommit": True, "connect_timeout": 5},
        )
    return _pool


@contextmanager
def connection() -> Iterator[Connection[DictRow]]:
    with get_pool().connection() as conn:
        yield conn
