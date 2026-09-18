"""iCalendar output for one event (contract v0.2 section 7.5), standard library only.

A fixture becomes a single VEVENT at its instant. A program becomes a weekly
recurring VEVENT (RRULE) with no end, anchored on the next occurrence of its
first weekday, because a calendar needs an instant to hang a rule on. Times
for programs are not published, so the entry is marked as an all-day
recurrence and the description says so.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
RRULE_DAY = {
    "monday": "MO",
    "tuesday": "TU",
    "wednesday": "WE",
    "thursday": "TH",
    "friday": "FR",
    "saturday": "SA",
    "sunday": "SU",
}


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545 line folding at 75 octets."""
    out: list[str] = []
    while len(line.encode("utf-8")) > 75:
        cut = 75
        while len(line[:cut].encode("utf-8")) > 75:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\r\n".join(out)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def next_weekday(after: date, weekday: str) -> date:
    target = WEEKDAY_INDEX[weekday]
    delta = (target - after.weekday()) % 7
    return after + timedelta(days=delta)


def build_ics(
    *,
    uid: str,
    summary: str,
    description: str,
    location: str | None,
    url: str,
    status: str,
    starts_at: datetime | None,
    ends_at: datetime | None,
    weekdays: tuple[str, ...],
    timezone: str,
    latitude: float | None,
    longitude: float | None,
    now: datetime | None = None,
    today: date | None = None,
) -> str:
    stamp = now or datetime.now(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SportAble Melbourne//Events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_stamp(stamp)}",
        f"SUMMARY:{_escape(summary)}",
    ]
    if starts_at is not None:
        end = ends_at or (starts_at + timedelta(hours=2))
        lines.append(f"DTSTART:{_stamp(starts_at)}")
        lines.append(f"DTEND:{_stamp(end)}")
    else:
        known = [d for d in weekdays if d in WEEKDAY_INDEX]
        anchor = (
            next_weekday(today or datetime.now(ZoneInfo(timezone)).date(), known[0])
            if known
            else (today or datetime.now(ZoneInfo(timezone)).date())
        )
        lines.append(f"DTSTART;VALUE=DATE:{anchor.strftime('%Y%m%d')}")
        if known:
            lines.append("RRULE:FREQ=WEEKLY;BYDAY=" + ",".join(RRULE_DAY[d] for d in known))
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if latitude is not None and longitude is not None:
        lines.append(f"GEO:{latitude:.6f};{longitude:.6f}")
    lines.append(f"DESCRIPTION:{_escape(description)}")
    lines.append(f"URL:{url}")
    lines.append(f"STATUS:{status}")
    lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
