"""Group venues by the facilities a person asked for, at the band they chose.

A venue is never dropped, only grouped (AC1.2.3): matched, undocumented
(nothing published, or recorded beyond the band) or not_available (a source
positively records the facility is not there).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.domain.facilities.rules import Presentation, presentations_for
from app.repositories.protocols import VenueRow

Verdict = Literal["pass", "open", "fail"]


def verdict(presentation: Presentation) -> Verdict:
    """pass = confirmed at the band, fail = a recorded absence, open = the rest."""
    if presentation.status == "confirmed":
        return "pass"
    if presentation.status == "not_available":
        return "fail"
    return "open"


@dataclass(frozen=True)
class Groups:
    """The three lists of §4. A venue is never dropped, only grouped."""

    matched: list[VenueRow]
    undocumented: list[VenueRow]
    not_available: list[VenueRow]


def group(venues: Sequence[VenueRow], kinds: Sequence[str], limit_m: int) -> Groups:
    """Partition by the requested kinds at the requested band (v0.2 §4).

    Unlike v0.1 ``partition``, venues with a recorded absence are listed as
    well as counted: a person who can use the nearby alternative still needs
    to find the venue.
    """
    if not kinds:
        return Groups(list(venues), [], [])
    matched: list[VenueRow] = []
    undocumented: list[VenueRow] = []
    not_available: list[VenueRow] = []
    for venue in venues:
        by_kind = {p.kind: p for p in presentations_for(venue, limit_m)}
        verdicts = {verdict(by_kind[kind]) for kind in kinds if kind in by_kind}
        if "fail" in verdicts:
            not_available.append(venue)
        elif "open" in verdicts:
            undocumented.append(venue)
        else:
            matched.append(venue)
    return Groups(matched, undocumented, not_available)
