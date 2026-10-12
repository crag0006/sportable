"""Regex layer for time hints (contract v0.3 section 7.7.2 and 7.7.4), prototype.

    uv run python -m lab.time_hints            # coverage over the local programs
    uv run python -m lab.time_hints --show 25  # print hints and misses

Pure functions over a description string; no database writes. A hint is a
clock time found in the text, with the sentence it came from. Nothing here
touches the structured fields.
"""

import argparse
import re
from dataclasses import dataclass, field

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEKDAY_RE = re.compile(r"\b(mon|tues?|wed(?:nes)?|thurs?|fri|sat(?:ur)?|sun)(?:day)?s?\b", re.I)
WEEKDAY_MAP = {
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

# 6:30pm, 6.30 pm, 6pm, 18:30, 10am, noon
CLOCK = r"(?:(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>am|pm|a\.m\.|p\.m\.)?|\b(?P<noon>noon|midday)\b)"
RANGE_RE = re.compile(
    r"(?P<start>"
    + CLOCK.replace("(?P<", "(?P<s_")
    + r")\s*(?:-|–|—|to|until|till|and)\s*(?P<end>"  # noqa: RUF001 - the dashes publishers type
    + CLOCK.replace("(?P<", "(?P<e_")
    + r")",
    re.I,
)
SINGLE_RE = re.compile(r"(?<![\d:.$])" + CLOCK + r"(?!\d|\.\d)", re.I)
# A sentence ends at . ! ? or a newline, but a dot between digits ("5.30") is part of a time.
SENTENCE_RE = re.compile(r"(?:[^.!?\n]|(?<=\d)\.(?=\d))+[.!?]?")
SLOT_WORDS = {
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


@dataclass
class Hint:
    start_local: str
    end_local: str | None
    weekdays: list[str]
    quote: str
    char_start: int
    char_end: int
    confidence: str
    slot: str = "main"
    basis: str = "regex"
    notes: list[str] = field(default_factory=list)


def _to_24h(h: str | None, m: str | None, ap: str | None, noon: str | None, other_ap: str | None = None) -> str | None:
    """A clock token as HH:MM, borrowing the other end's am/pm when this one has none."""
    if noon:
        return "12:00"
    if h is None:
        return None
    hour, minute = int(h), int(m or 0)
    if hour > 23 or minute > 59:
        return None
    ap = (ap or other_ap or "").replace(".", "").lower()
    if ap == "pm" and hour < 12:
        hour += 12
    if ap == "am" and hour == 12:
        hour = 0
    if not ap and m is None and hour <= 7:
        # "6 to 8" with no am/pm and no minutes: ambiguous, no hint
        return None
    if not ap and 1 <= hour <= 7:
        hour += 12  # "5.30-6.30" in a sport listing is the evening
    return f"{hour:02d}:{minute:02d}"


def _weekdays_in(text: str, before: int | None = None) -> list[str]:
    """Weekday names in a sentence, in calendar order.

    With ``before``, the nearest weekday mention preceding that offset wins
    ("Fridays 6pm-7:30pm Saturdays 9am-10:30am" binds each time to its own day);
    the whole sentence is the fallback.
    """
    mentions = [(m.start(), WEEKDAY_MAP.get(m.group(1).lower(), m.group(1).lower())) for m in WEEKDAY_RE.finditer(text)]
    if before is not None:
        prior = [d for pos, d in mentions if pos < before]
        if prior and len({d for _, d in mentions}) > 1:
            return [prior[-1]]
    found = {d for _, d in mentions}
    return [d for d in WEEKDAYS if d in found]


def _slot_in(text: str) -> str:
    """A slot label when the sentence names an audience."""
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in SLOT_WORDS:
            return SLOT_WORDS[w]
    return "main"


def _quote(sentence: str, start: int, end: int, width: int = 70) -> str:
    """The sentence, or a window around the match when stripped HTML left a run-on sentence."""
    if len(sentence) <= 2 * width:
        return sentence.strip()
    a, b = max(0, start - width), min(len(sentence), end + width)
    return ("..." if a > 0 else "") + sentence[a:b].strip() + ("..." if b < len(sentence) else "")


def hints_for(description: str, published_weekdays: list[str] | None = None) -> list[Hint]:
    """Every clock time in the description, each with its sentence, weekdays and slot."""
    out: list[Hint] = []
    if not description:
        return out
    for s in SENTENCE_RE.finditer(description):
        sentence = s.group(0)
        base = s.start()
        taken: list[tuple[int, int]] = []
        # Nearest-day binding only when the sentence carries several times; one
        # time after a list of days applies to all of them.
        spans = [m.span() for m in RANGE_RE.finditer(sentence)]
        singles = [
            m
            for m in SINGLE_RE.finditer(sentence)
            if (m.group("ap") or m.group("noon")) and not any(a <= m.start() < b for a, b in spans)
        ]
        several = len(spans) + len(singles) > 1
        for m in RANGE_RE.finditer(sentence):
            start = _to_24h(m.group("s_h"), m.group("s_m"), m.group("s_ap"), m.group("s_noon"), m.group("e_ap"))
            end = _to_24h(m.group("e_h"), m.group("e_m"), m.group("e_ap"), m.group("e_noon"), m.group("s_ap"))
            if start is None or end is None:
                continue
            if end <= start and (m.group("e_ap") or "").lower().startswith("p") is False and m.group("s_ap") is None:
                # "11 to 1pm": start borrowed pm wrongly; retry start as am
                start = _to_24h(m.group("s_h"), m.group("s_m"), "am", None)
            if start is None or end is None or end <= start:
                continue
            taken.append(m.span())
            out.append(
                Hint(
                    start,
                    end,
                    _weekdays_in(sentence, m.start() if several else None) or list(published_weekdays or []),
                    _quote(sentence, m.start(), m.end()),
                    base + m.start(),
                    base + m.end(),
                    "high",
                    _slot_in(sentence),
                )
            )
        for m in SINGLE_RE.finditer(sentence):
            if any(a <= m.start() < b for a, b in taken):
                continue
            if not (m.group("ap") or m.group("noon")):
                continue  # a bare number is a count, a price or an age, not a time
            start = _to_24h(m.group("h"), m.group("m"), m.group("ap"), m.group("noon"))
            if start is None or any(
                start in (h.start_local, h.end_local) and h.quote == _quote(sentence, m.start(), m.end()) for h in out
            ):
                continue  # "10:30-12 midday": the trailing "midday" is the range's own end, not a second time
            out.append(
                Hint(
                    start,
                    None,
                    _weekdays_in(sentence, m.start() if several else None) or list(published_weekdays or []),
                    _quote(sentence, m.start(), m.end()),
                    base + m.start(),
                    base + m.end(),
                    "medium",
                    _slot_in(sentence),
                )
            )
    return out


def main() -> None:
    """Coverage over the local database and samples of hits and misses."""
    import psycopg

    from lab import config

    p = argparse.ArgumentParser()
    p.add_argument("--show", type=int, default=12)
    args = p.parse_args()
    with psycopg.connect(config.require("DATABASE_URL")) as conn:
        rows = conn.execute(
            "select program_id, name, description, recurrence_weekdays from program"
            " where description is not null order by program_id"
        ).fetchall()
    # A time word, excluding prices ("$10.80", "6.50 concession").
    mention = re.compile(
        r"(?<![$\d.])\b\d{1,2}\s*(?:am|pm)\b|(?<![$\d.])\b\d{1,2}[:.]\d{2}\b(?!\s*(?:full|concession|per|each))|\bnoon\b",
        re.I,
    )
    hit = both = mentions = missed = 0
    samples, misses = [], []
    for _pid, name, desc, wds in rows:
        hs = hints_for(desc, list(wds or []))
        has_mention = bool(mention.search(desc))
        mentions += has_mention
        if hs:
            hit += 1
            both += any(h.end_local for h in hs)
            samples.append((name, hs))
        elif has_mention:
            missed += 1
            misses.append(
                (
                    name,
                    mention.search(desc).group(0),
                    desc[max(0, mention.search(desc).start() - 60) : mention.search(desc).start() + 60].replace(
                        "\n", " "
                    ),
                )
            )
    print(
        f"programs {len(rows)}: with a clock-time mention {mentions}; regex hints for {hit}"
        f" ({both} with an end time); mentions without a hint {missed}"
    )
    print("\n--- sample hits")
    for name, hs in samples[: args.show]:
        for h in hs[:2]:
            print(
                f"  {name[:34]:34s} {h.slot:9s} {h.start_local}-{h.end_local or '?'} {h.weekdays}"
                f' [{h.confidence}]  "{h.quote[:90]}"'
            )
    print("\n--- mentions the regex did not turn into a hint")
    for name, tok, ctx in misses[: args.show]:
        print(f"  {name[:34]:34s} token {tok!r}: ...{ctx}...")


if __name__ == "__main__":
    main()
