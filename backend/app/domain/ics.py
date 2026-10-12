"""iCalendar output for events (contract v0.3 sections 7.5 and 7.6), standard library only.

A fixture is one VEVENT at its instant (UTC). A program is a weekly recurring
VEVENT: timed, in the site's timezone with a VTIMEZONE block so the entry stays
at the published local time across the daylight-saving change, when a time
hint exists; all-day otherwise. Programs with several time hints become one
VEVENT per hint, each with its own UID.
"""

from datetime import UTC, date, datetime, time, timedelta
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
PRODID = "-//SportAble Melbourne//Events//EN"
DEFAULT_DURATION = timedelta(minutes=60)

# Australia/Melbourne: AEST +10:00, AEDT +11:00, daylight time from the first
# Sunday in October to the first Sunday in April.
VTIMEZONE: dict[str, list[str]] = {
    "Australia/Melbourne": [
        "BEGIN:VTIMEZONE",
        "TZID:Australia/Melbourne",
        "BEGIN:STANDARD",
        "DTSTART:19700405T030000",
        "RRULE:FREQ=YEARLY;BYMONTH=4;BYDAY=1SU",
        "TZOFFSETFROM:+1100",
        "TZOFFSETTO:+1000",
        "TZNAME:AEST",
        "END:STANDARD",
        "BEGIN:DAYLIGHT",
        "DTSTART:19701004T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=1SU",
        "TZOFFSETFROM:+1000",
        "TZOFFSETTO:+1100",
        "TZNAME:AEDT",
        "END:DAYLIGHT",
        "END:VTIMEZONE",
    ]
}


def _escape(text: str) -> str:
    """RFC 5545 text escaping: backslash, semicolon, comma and newline."""
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
    """A UTC timestamp in the ``YYYYMMDDTHHMMSSZ`` form the format requires."""
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _local(day: date, clock: str) -> str:
    """A floating local timestamp ``YYYYMMDDTHHMMSS`` for a ``TZID`` property."""
    hh, mm = clock.split(":")
    return f"{day.strftime('%Y%m%d')}T{int(hh):02d}{int(mm):02d}00"


def next_weekday(after: date, weekday: str) -> date:
    """The first ``weekday`` on or after ``after``."""
    target = WEEKDAY_INDEX[weekday]
    delta = (target - after.weekday()) % 7
    return after + timedelta(days=delta)


def rrule(weekdays: tuple[str, ...]) -> str | None:
    """``FREQ=WEEKLY;BYDAY=...`` for the known weekdays, or None when there are none."""
    known = [RRULE_DAY[d] for d in weekdays if d in RRULE_DAY]
    return "FREQ=WEEKLY;BYDAY=" + ",".join(known) if known else None


def _end_clock(start: str, end: str | None) -> str:
    """The end time, or the start plus the default duration, as HH:MM."""
    if end:
        return end
    base = datetime.combine(date(2000, 1, 3), time.fromisoformat(start)) + DEFAULT_DURATION
    return base.strftime("%H:%M")


def when_lines(
    *,
    starts_at: datetime | None,
    ends_at: datetime | None,
    weekdays: tuple[str, ...],
    anchor: date,
    start_local: str | None,
    end_local: str | None,
    timezone: str,
) -> list[str]:
    """DTSTART/DTEND for a fixture; a timed or all-day weekly rule for a program."""
    if starts_at is not None:
        end = ends_at or (starts_at + timedelta(hours=2))
        return [f"DTSTART:{_stamp(starts_at)}", f"DTEND:{_stamp(end)}"]
    rule = rrule(weekdays)
    if start_local and timezone in VTIMEZONE:
        lines = [
            f"DTSTART;TZID={timezone}:{_local(anchor, start_local)}",
            f"DTEND;TZID={timezone}:{_local(anchor, _end_clock(start_local, end_local))}",
        ]
    else:
        lines = [f"DTSTART;VALUE=DATE:{anchor.strftime('%Y%m%d')}"]
    if rule:
        lines.append(f"RRULE:{rule}")
    return lines


def _where_lines(
    location: str | None, latitude: float | None, longitude: float | None
) -> list[str]:
    """LOCATION and GEO, each only when known."""
    lines: list[str] = []
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if latitude is not None and longitude is not None:
        lines.append(f"GEO:{latitude:.6f};{longitude:.6f}")
    return lines


def vevent_lines(
    *,
    uid: str,
    summary: str,
    description: str,
    location: str | None,
    url: str,
    status: str,
    when: list[str],
    latitude: float | None,
    longitude: float | None,
    stamp: datetime,
    sequence: int = 0,
) -> list[str]:
    """One VEVENT, unfolded. ``when`` comes from ``when_lines``."""
    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_stamp(stamp)}",
        f"LAST-MODIFIED:{_stamp(stamp)}",
        f"SEQUENCE:{sequence}",
        f"SUMMARY:{_escape(summary)}",
        *when,
        *_where_lines(location, latitude, longitude),
        f"DESCRIPTION:{_escape(description)}",
        f"URL:{url}",
        f"STATUS:{status}",
        "END:VEVENT",
    ]


def build_calendar(
    events: list[list[str]],
    *,
    timezone: str,
    name: str | None = None,
    description: str | None = None,
) -> str:
    """One VCALENDAR around the given VEVENT line lists, folded to RFC 5545 line length."""
    head = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    if name:
        head.append(f"X-WR-CALNAME:{_escape(name)}")
    if description:
        head.append(f"X-WR-CALDESC:{_escape(description)}")
    head.append(f"X-WR-TIMEZONE:{timezone}")
    lines = head + VTIMEZONE.get(timezone, [])
    for event in events:
        lines.extend(event)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def today_in(timezone: str, now: datetime | None) -> date:
    """Today's local date, from ``now`` when given."""
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone)).date()
