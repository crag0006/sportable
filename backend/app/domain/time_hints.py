"""Clock times read from a program description (contract v0.3 section 7.7.2).

The structured source publishes a weekday and a time-of-day label, never a
clock time, yet most descriptions state one ("Fridays 6pm-7:30pm"). A time
hint is such a time, kept with the sentence it came from, so a calendar entry
can offer it with its quote. Nothing here is promoted into ``starts_at`` or
``time_local``: a hint is the publisher's prose, shown as such.

Pure functions over the description text; the regex layer of section 7.7.4.
"""

import re
from dataclasses import dataclass

WEEKDAYS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_WEEKDAY_RE = re.compile(r"\b(mon|tues?|wed(?:nes)?|thurs?|fri|sat(?:ur)?|sun)(?:day)?s?\b", re.I)
_WEEKDAY_MAP = {
    "mon": "monday",
    "tue": "tuesday",
    "tues": "tuesday",
    "wed": "wednesday",
    "wednes": "wednesday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "fri": "friday",
    "sat": "saturday",
    "satur": "saturday",
    "sun": "sunday",
}
# 6:30pm, 6.30 pm, 6pm, 18:30, noon
_CLOCK = (
    r"(?:(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>am|pm|a\.m\.|p\.m\.)?"
    r"|\b(?P<noon>noon|midday)\b)"
)
_RANGE_RE = re.compile(
    r"(?P<start>"
    + _CLOCK.replace("(?P<", "(?P<s_")
    + r")\s*(?:-|–|—|to|until|till|and)\s*(?P<end>"  # noqa: RUF001 - the dashes publishers type
    + _CLOCK.replace("(?P<", "(?P<e_")
    + r")",
    re.I,
)
_SINGLE_RE = re.compile(r"(?<![\d:.$])" + _CLOCK + r"(?!\d|\.\d)", re.I)
# A sentence ends at . ! ? or a newline; a dot between digits ("5.30") is part of a time.
_SENTENCE_RE = re.compile(r"(?:[^.!?\n]|(?<=\d)\.(?=\d))+[.!?]?")
_SLOT_WORDS = {
    "adult": "adults",
    "adults": "adults",
    "junior": "juniors",
    "juniors": "juniors",
    "kids": "juniors",
    "children": "juniors",
    "youth": "youth",
    "senior": "seniors",
    "seniors": "seniors",
    "beginner": "beginners",
    "beginners": "beginners",
}
_QUOTE_WIDTH = 70


@dataclass(frozen=True)
class TimeHint:
    """One clock time found in the text, with its provenance."""

    slot: str
    start_local: str
    end_local: str | None
    weekdays: tuple[str, ...]
    quote: str
    char_start: int
    char_end: int
    confidence: str  # high (start and end), medium (start only)
    basis: str = "regex"


def _to_24h(
    h: str | None, m: str | None, ap: str | None, noon: str | None, other: str | None
) -> str | None:
    """A clock token as HH:MM, borrowing the other end's am/pm when this one has none."""
    if noon:
        return "12:00"
    if h is None:
        return None
    hour, minute = int(h), int(m or 0)
    if hour > 23 or minute > 59:
        return None
    marker = (ap or other or "").replace(".", "").lower()
    if marker == "pm" and hour < 12:
        hour += 12
    if marker == "am" and hour == 12:
        hour = 0
    if not marker and m is None and hour <= 7:
        return None  # "6 to 8" with no am/pm and no minutes: ambiguous, no hint
    if not marker and 1 <= hour <= 7:
        hour += 12  # "5.30-6.30" in a sport listing is the evening
    return f"{hour:02d}:{minute:02d}"


def _weekdays_in(text: str, before: int | None = None) -> tuple[str, ...]:
    """Weekday names in a sentence, in calendar order.

    With ``before``, the nearest weekday mention preceding that offset wins
    ("Fridays 6pm-7:30pm Saturdays 9am-10:30am" binds each time to its day);
    the whole sentence is the fallback.
    """
    mentions = [
        (x.start(), _WEEKDAY_MAP.get(x.group(1).lower(), x.group(1).lower()))
        for x in _WEEKDAY_RE.finditer(text)
    ]
    if before is not None:
        prior = [d for pos, d in mentions if pos < before]
        if prior and len({d for _, d in mentions}) > 1:
            return (prior[-1],)
    found = {d for _, d in mentions}
    return tuple(d for d in WEEKDAYS if d in found)


def _slot_in(text: str) -> str:
    """A slot label when the sentence names an audience, else ``main``."""
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in _SLOT_WORDS:
            return _SLOT_WORDS[word]
    return "main"


def _quote(sentence: str, start: int, end: int) -> str:
    """The sentence, or a window around the match when stripped HTML left a run-on sentence."""
    if len(sentence) <= 2 * _QUOTE_WIDTH:
        return sentence.strip()
    a, b = max(0, start - _QUOTE_WIDTH), min(len(sentence), end + _QUOTE_WIDTH)
    return ("..." if a > 0 else "") + sentence[a:b].strip() + ("..." if b < len(sentence) else "")


def _hint(
    sentence: str, base: int, m: re.Match[str], start: str, end: str | None, days: tuple[str, ...]
) -> TimeHint:
    """A hint for one match inside a sentence that starts at ``base`` in the description."""
    return TimeHint(
        slot=_slot_in(sentence),
        start_local=start,
        end_local=end,
        weekdays=days,
        quote=_quote(sentence, m.start(), m.end()),
        char_start=base + m.start(),
        char_end=base + m.end(),
        confidence="high" if end else "medium",
    )


def _range_hints(
    sentence: str, base: int, several: bool, published: tuple[str, ...]
) -> list[TimeHint]:
    """Start-to-end ranges in one sentence."""
    out: list[TimeHint] = []
    for m in _RANGE_RE.finditer(sentence):
        start = _to_24h(
            m.group("s_h"), m.group("s_m"), m.group("s_ap"), m.group("s_noon"), m.group("e_ap")
        )
        end = _to_24h(
            m.group("e_h"), m.group("e_m"), m.group("e_ap"), m.group("e_noon"), m.group("s_ap")
        )
        if start is not None and end is not None and end <= start and m.group("s_ap") is None:
            start = _to_24h(m.group("s_h"), m.group("s_m"), "am", None, None)  # "11 to 1pm"
        if start is None or end is None or end <= start:
            continue
        days = _weekdays_in(sentence, m.start() if several else None) or published
        out.append(_hint(sentence, base, m, start, end, days))
    return out


def _single_hints(
    sentence: str,
    base: int,
    spans: list[tuple[int, int]],
    several: bool,
    published: tuple[str, ...],
    found: list[TimeHint],
) -> list[TimeHint]:
    """Lone times with am/pm or noon, outside the ranges already taken."""
    out: list[TimeHint] = []
    for m in _SINGLE_RE.finditer(sentence):
        if any(a <= m.start() < b for a, b in spans) or not (m.group("ap") or m.group("noon")):
            continue
        start = _to_24h(m.group("h"), m.group("m"), m.group("ap"), m.group("noon"), None)
        quote = _quote(sentence, m.start(), m.end())
        if start is None or any(
            start in (h.start_local, h.end_local) and h.quote == quote for h in found
        ):
            continue  # "10:30-12 midday": the trailing "midday" is the range's own end
        days = _weekdays_in(sentence, m.start() if several else None) or published
        out.append(_hint(sentence, base, m, start, None, days))
    return out


def hints_for(description: str | None, published_weekdays: tuple[str, ...] = ()) -> list[TimeHint]:
    """Every clock time in the description, each with its sentence, weekdays and slot."""
    out: list[TimeHint] = []
    for s in _SENTENCE_RE.finditer(description or ""):
        sentence, base = s.group(0), s.start()
        spans = [m.span() for m in _RANGE_RE.finditer(sentence)]
        singles = [
            m
            for m in _SINGLE_RE.finditer(sentence)
            if (m.group("ap") or m.group("noon")) and not any(a <= m.start() < b for a, b in spans)
        ]
        several = len(spans) + len(singles) > 1
        ranges = _range_hints(sentence, base, several, published_weekdays)
        out.extend(ranges)
        out.extend(_single_hints(sentence, base, spans, several, published_weekdays, ranges))
    return out


def hint_for_weekday(hints: list[TimeHint], weekday: str | None) -> TimeHint | None:
    """The hint that applies to a weekday: the first naming it, else the first of all."""
    if not hints:
        return None
    if weekday:
        for h in hints:
            if weekday in h.weekdays:
                return h
    return hints[0]
