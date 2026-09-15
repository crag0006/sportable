"""Provenance on every fact (HLD principle 3, AC1.3.2, AC3.3.2, AC3.3.3).

A ``SourceRef`` is what every facility, corridor facility and event carries:
who published it, when they last updated it, when we fetched it, and whether
the publisher's date is older than the source's own staleness threshold.

``possibly_out_of_date`` is a warning, never a verdict. The date stays on
screen next to it so the person decides how much to trust the fact.
"""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class SourceRef:
    id: str | None
    name: str
    publisher_last_updated: date | None
    retrieved_at: date | None
    possibly_out_of_date: bool
    stale_after_days: int


def _as_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def is_stale(publisher_last_updated: date | None, stale_after_days: int, today: date) -> bool:
    """Older than the threshold, or undated. An undated fact cannot be vouched for."""
    if publisher_last_updated is None:
        return True
    return (today - publisher_last_updated).days > stale_after_days


def source_ref(
    name: str | None,
    *,
    source_id: str | None = None,
    publisher_last_updated: date | datetime | None = None,
    retrieved_at: date | datetime | None = None,
    stale_after_days: int | None = None,
    default_stale_after_days: int = 365,
    today: date | None = None,
) -> SourceRef | None:
    """Build the reference, or ``None`` when there is no source at all.

    ``stale_after_days`` comes from the source register when the column exists
    and from config otherwise; the value actually applied is echoed back so the
    interface can say "older than 365 days" rather than "old".
    """
    if not name:
        return None
    threshold = stale_after_days if stale_after_days is not None else default_stale_after_days
    updated = _as_date(publisher_last_updated)
    return SourceRef(
        id=source_id,
        name=name,
        publisher_last_updated=updated,
        retrieved_at=_as_date(retrieved_at),
        possibly_out_of_date=is_stale(updated, threshold, today or date.today()),
        stale_after_days=threshold,
    )
