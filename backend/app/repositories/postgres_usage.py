"""The daily assistant counter over ``assistant_usage`` (migration 015)."""

from datetime import date
from typing import Any

from app.core.db import connection

SQL_RECORD = """
INSERT INTO assistant_usage (day, calls) VALUES (%(day)s, 1)
ON CONFLICT (day) DO UPDATE SET calls = assistant_usage.calls + 1
RETURNING calls
"""
SQL_HAS_TABLE = "SELECT to_regclass('public.assistant_usage') IS NOT NULL AS present"


class PostgresUsageRepository:
    """``UsageRepository``; the table is looked for once per process."""

    def __init__(self) -> None:
        """Nothing is opened until the first turn."""
        self._present: bool | None = None

    def _available(self, conn: Any) -> bool:
        """Whether migration 015 has been applied here."""
        if self._present is None:
            self._present = bool(conn.execute(SQL_HAS_TABLE).fetchone()["present"])
        return self._present

    def record_call(self, day: date) -> int | None:
        """One more turn on ``day``; the day's total, or None without the table."""
        with connection() as conn:
            if not self._available(conn):
                return None
            row = conn.execute(SQL_RECORD, {"day": day}).fetchone()
            return int(row["calls"]) if row else None
