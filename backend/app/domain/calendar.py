"""The ``calendar`` block on every event (contract v0.3 section 7.7).

The frontend builds every calendar entry from this block and nothing else, so
the chat panel, the saved list and the event page export identical entries.
The Google "new event" link carries the whole entry: Google fetches nothing
from us and we store nothing about the user.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.domain.ics import _end_clock, next_weekday, rrule
from app.domain.time_hints import WEEKDAYS, TimeHint, hint_for_weekday
from app.repositories.protocols import EventRow
from app.schemas.events import CalendarLinkOut, CalendarOut, EventOut, TimeHintOut

DEFAULT_DURATION_MINUTES = 60
FIXTURE_DEFAULT_LENGTH = timedelta(hours=2)
GOOGLE_TEMPLATE = "https://calendar.google.com/calendar/render"
REASON_MESSAGES: dict[str, str] = {
    "no_weekday_published": (
        "The provider has not published which day this runs, so it cannot be added to a calendar. "
        "The publisher page may say more."
    ),
    "cancelled": "This event is cancelled, so it is not offered for a calendar.",
    "finished": "This event has finished, so it is not offered for a calendar.",
}
TIME_NOT_PUBLISHED = "Exact time not published by the provider."
CHECK_TIME = "Check the time with the provider."


def decision(row: EventRow) -> tuple[bool, str | None, str | None]:
    """``(exportable, mode, reason)`` per the decision table of section 7.7.1."""
    if row.status in ("CANCELLED", "ABANDONED"):
        return False, None, "cancelled"
    if row.kind == "fixture":
        if row.status == "FINAL":
            return False, None, "finished"
        return True, "single", None
    if not any(d in WEEKDAYS for d in row.weekdays):
        return False, None, "no_weekday_published"
    return True, "weekly", None


def hint_out(h: TimeHint) -> TimeHintOut:
    """A hint as the contract shows it."""
    return TimeHintOut(
        slot=h.slot,
        start_local=h.start_local,
        end_local=h.end_local,
        weekdays=list(h.weekdays),
        basis=h.basis,
        quote=h.quote,
        char_start=h.char_start,
        char_end=h.char_end,
        confidence=h.confidence,
    )


def slot_hints(
    hints: list[TimeHint], days: tuple[str, ...], fallback: TimeHint | None
) -> list[TimeHint | None]:
    """The slots an event gets an entry for: each hint on a published weekday, else the fallback."""
    on_days: list[TimeHint | None] = [h for h in hints if days and set(h.weekdays) & set(days)]
    return on_days or [fallback]


def _own_days(slot: TimeHint | None, days: tuple[str, ...]) -> tuple[str, ...]:
    """The published weekdays a slot covers: the hint's own, else all of them."""
    return tuple(d for d in days if slot and d in slot.weekdays) or days


def _days_key(own: tuple[str, ...]) -> str:
    """``friday``, ``wednesday-friday``, ``daily`` for all seven, ``main`` for none."""
    if len(own) == len(WEEKDAYS):
        return "daily"
    return "-".join(own) or "main"


def _days_text(own: tuple[str, ...]) -> str:
    """``Friday``, ``Monday, Wednesday and Friday``, ``Every day`` for all seven."""
    if len(own) == len(WEEKDAYS):
        return "Every day"
    names = [d.capitalize() for d in own]
    return " and ".join(p for p in (", ".join(names[:-1]), names[-1]) if p) if names else ""


def slot_keys(slots: Sequence[TimeHint | None], days: tuple[str, ...]) -> list[str]:
    """A short key per slot, distinct within the event; the ``.ics`` UID suffix uses it too.

    One slot keeps its own label (``main`` or ``juniors``). With several, a plain
    hint is keyed by its weekdays (``friday``) and a repeat gets ``-2``, ``-3``:
    two plain sentences both label their hint ``main``, and calendar apps treat
    entries with one UID as one event, so a shared key hid the second slot on
    import (found by the frontend).
    """
    if len(slots) == 1:
        return [slots[0].slot if slots[0] else "main"]
    keys: list[str] = []
    counts: dict[str, int] = {}
    for slot in slots:
        base = slot.slot if slot and slot.slot != "main" else _days_key(_own_days(slot, days))
        counts[base] = counts.get(base, 0) + 1
        keys.append(base if counts[base] == 1 else f"{base}-{counts[base]}")
    return keys


def _clock12(clock: str) -> str:
    """``19:00`` as ``7:00 pm``."""
    hh, mm = (int(part) for part in clock.split(":"))
    return f"{(hh % 12) or 12}:{mm:02d} {'am' if hh < 12 else 'pm'}"


def _timing_line(out: EventOut, hint: TimeHint | None) -> str:
    """The entry's first description line: when it runs, and where the time came from."""
    if out.recurrence is None:
        when = f"{out.date_local} {out.time_local or ''}".strip() if out.date_local else None
        return f"Starts {when} ({out.timezone})." if when else "Date not published."
    summary = out.recurrence.summary + "."
    if hint is None:
        return f"{summary} {TIME_NOT_PUBLISHED}"
    return f'{summary} The publisher\'s description says: "{hint.quote}". {CHECK_TIME}'


def description_lines(out: EventOut, hint: TimeHint | None, event_url: str) -> list[str]:
    """The entry's description, one line each, from the same tiles as the page (AC5.1.3)."""
    lines = [_timing_line(out, hint)]
    if out.recurrence is None and out.starts_at and not out.ends_at:
        lines.append("End time is estimated.")
    lines.extend(f"{tile.label}: {tile.message}" for tile in out.access.facilities)
    if out.venue.name and not out.venue.matched and out.venue.message:
        lines.append(out.venue.message)
    lines.append(f"Event page: {event_url}")
    lines.append(f"Publisher page: {out.links.external}")
    if out.source.attribution:
        lines.append(out.source.attribution)
    return lines


def _google_dates(row: EventRow, anchor: date | None, hint: TimeHint | None) -> str:
    """The ``dates`` parameter: a timed pair, or an all-day pair, in local floating time."""
    if row.starts_at is not None:
        tz = ZoneInfo(row.timezone)
        start = row.starts_at.astimezone(tz)
        end = row.ends_at.astimezone(tz) if row.ends_at else start + FIXTURE_DEFAULT_LENGTH
        return f"{start:%Y%m%dT%H%M%S}/{end:%Y%m%dT%H%M%S}"
    assert anchor is not None
    if hint is None:
        return f"{anchor:%Y%m%d}/{anchor + timedelta(days=1):%Y%m%d}"
    opens = hint.start_local.replace(":", "") + "00"
    closes = _end_clock(hint.start_local, hint.end_local).replace(":", "") + "00"
    return f"{anchor:%Y%m%d}T{opens}/{anchor:%Y%m%d}T{closes}"


def google_template_url(
    *,
    title: str,
    dates: str,
    timezone: str,
    rule: str | None,
    location: str | None,
    details: Sequence[str],
) -> str:
    """The Google Calendar "new event" page, prefilled. No OAuth; the user presses Save."""
    params: dict[str, str] = {"action": "TEMPLATE", "text": title, "dates": dates, "ctz": timezone}
    if rule:
        params["recur"] = f"RRULE:{rule}"
    if location:
        params["location"] = location
    params["details"] = "\n".join(details)
    return GOOGLE_TEMPLATE + "?" + urlencode(params)


@dataclass(frozen=True)
class _Entry:
    """What every Google link of one event shares."""

    row: EventRow
    title: str
    location: str | None
    lines: list[str]
    days: tuple[str, ...]
    anchor: date | None


def _slot_label(entry: _Entry, out: EventOut, h: TimeHint | None) -> str:
    """What the button for one slot says: audience, weekday(s) and the hinted times."""
    if entry.row.kind != "program":
        return " ".join(p for p in (out.date_local, out.time_local) if p) or entry.title
    days = _days_text(_own_days(h, entry.days))
    if h is None:
        return f"{days}, time not published"
    times = (
        f"{_clock12(h.start_local)} to {_clock12(h.end_local)}"
        if h.end_local
        else f"from {_clock12(h.start_local)}"
    )
    who = f"{h.slot.capitalize()}, " if h.slot != "main" else ""
    return f"{who}{days} {times}"


def _slot_links(
    entry: _Entry, out: EventOut, hints: list[TimeHint], hint: TimeHint | None
) -> list[CalendarLinkOut]:
    """One Google link per time slot on a published weekday; one all-day link otherwise."""
    slots = slot_hints(hints, entry.days, hint)
    links: list[CalendarLinkOut] = []
    for h, key in zip(slots, slot_keys(slots, entry.days), strict=True):
        url = google_template_url(
            title=entry.title,
            dates=_google_dates(entry.row, entry.anchor, h),
            timezone=entry.row.timezone,
            rule=rrule(_own_days(h, entry.days)) if entry.row.kind == "program" else None,
            location=entry.location,
            details=entry.lines,
        )
        links.append(CalendarLinkOut(slot=key, label=_slot_label(entry, out, h), url=url))
    return links


def _entry(row: EventRow, out: EventOut, hint: TimeHint | None, today: date, base: str) -> _Entry:
    """What every link and the file share: title, place, description lines, days, anchor."""
    days = tuple(d for d in WEEKDAYS if d in row.weekdays)
    sport = out.sport or out.sport_raw
    return _Entry(
        row=row,
        title=f"{sport}: {out.title}" if sport else out.title,
        location=", ".join(p for p in (out.venue.name, out.venue.address) if p) or None,
        lines=description_lines(out, hint, f"{base}/events/{row.event_id}"),
        days=days,
        anchor=next_weekday(today, days[0]) if days else None,
    )


def _schedule(row: EventRow, out: EventOut, entry: _Entry, mode: str | None) -> dict[str, object]:
    """The when-fields of the block: rule and first date for a program, instants for a fixture."""
    weekly = mode == "weekly"
    return {
        "weekdays": list(entry.days),
        "rrule": rrule(entry.days) if weekly else None,
        "first_date": entry.anchor.isoformat() if entry.anchor and weekly else None,
        "start": out.starts_at,
        "end": out.ends_at,
        "time_published": row.starts_at is not None,
        "time_of_day": list(row.time_of_day),
        "timezone": row.timezone,
        "default_duration_minutes": DEFAULT_DURATION_MINUTES,
    }


def calendar_out(
    row: EventRow, out: EventOut, hints: list[TimeHint], today: date, base_url: str
) -> CalendarOut:
    """The block for one event. ``hints`` are the regex hints over the description."""
    exportable, mode, reason = decision(row)
    days = tuple(d for d in WEEKDAYS if d in row.weekdays)
    hint = hint_for_weekday(hints, days[0] if days else None)
    entry = _entry(row, out, hint, today, base_url)
    links = _slot_links(entry, out, hints, hint) if exportable else []
    return CalendarOut(
        exportable=exportable,
        reason=reason,
        message=REASON_MESSAGES.get(reason or ""),
        mode=mode,
        title=entry.title,
        **_schedule(row, out, entry, mode),
        time_hint=hint_out(hint) if hint else None,
        time_hints=[hint_out(h) for h in hints],
        location=entry.location,
        description_lines=entry.lines,
        event_url=f"{base_url}/events/{row.event_id}",
        ics_url=f"/api/v1/events/{row.event_id}.ics",
        google_template_url=links[0].url if links else None,
        google_template_urls=[link.url for link in links],
        google_template_links=links,
        dedupe_key=f"sportable:{row.event_id}"
        + (f":{hint.slot}" if hint and hint.slot != "main" else ""),
    )
