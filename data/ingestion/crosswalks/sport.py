"""
ingestion/crosswalks/sport.py

Reads the reviewed sport crosswalk and answers questions about it.

WHY THIS IS A SEPARATE MODULE AND NOT PART OF THE TRANSFORMER
    ds09_aaaplay.transform() does no file, database or network access, and that
    property is worth more than the convenience of having it read this YAML
    itself. The crosswalk is loaded by whoever calls the transformer and handed
    in, so the transformer stays a pure function of its arguments and the tests
    keep running with no filesystem at all.

WHAT IT IS FOR
    program_sport.sport_key holds the publisher's own term. This turns that term
    into the sport or sports a venue search would recognise, and — just as
    importantly — tells the caller when a term is not in the reviewed file at
    all, so a new upstream term surfaces as a quarantine row rather than
    disappearing.

WHAT IT DELIBERATELY WILL NOT DO
    There is no fallback guess. A term absent from the file resolves to nothing
    and is reported as unknown. Guessing here — lower-case and compare, prefix
    match, trigram similarity — is what maps Gym onto Gymnastics and Boccia onto
    Bocce, and a wrong sport in front of somebody choosing a venue is the error
    the whole crosswalk exists to prevent. See the header of the YAML.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CROSSWALK_PATH = Path(__file__).with_name("ds09_sport_vocabulary.yaml")

# The relations the reviewed file may use. Registered here rather than accepted
# as free text, so a typo in the YAML fails a test instead of quietly creating a
# ninth category nobody reads.
RELATIONS = frozenset(
    {
        "exact",
        "alias",
        "narrower",
        "compound",
        "split",
        "added",
        "added_adaptive",
        "not_a_sport",
        "unmapped",
    }
)

# Relations whose target is a NEW vocabulary entry rather than an existing one.
# Checked against venue_vocabulary in validate(): an "added" row whose target is
# already in the vocabulary is a mislabelled alias, and an alias whose target is
# not in the vocabulary is a typo.
ADDED_RELATIONS = frozenset({"added", "added_adaptive"})

# Relations that carry no vocabulary target at all, and are expected not to.
UNTARGETED_RELATIONS = frozenset({"not_a_sport", "unmapped"})


class CrosswalkError(ValueError):
    """Raised when the reviewed crosswalk file does not hold together."""


@dataclass(frozen=True)
class SportTerm:
    """One reviewed publisher term."""

    term: str
    term_key: str
    publisher_slug: str
    publisher_term_id: int
    activity_count: int
    relation: str
    maps_to: tuple[str, ...]
    note: str

    @property
    def is_adaptive(self) -> bool:
        """Whether this term is an adaptive or para sport held apart on purpose.

        These carry exactly one target, themselves, and never a row to a
        non-adaptive parent. Anything that starts folding vocabulary entries
        together must read this flag first.
        """
        return self.relation == "added_adaptive"

    @property
    def adds_to_vocabulary(self) -> bool:
        return self.relation in ADDED_RELATIONS


class SportCrosswalk:
    """The reviewed crosswalk, indexed by the key program_sport is keyed on."""

    def __init__(
        self,
        terms: list[SportTerm],
        venue_vocabulary: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.terms = tuple(terms)
        self.venue_vocabulary = tuple(venue_vocabulary)
        self.metadata = metadata or {}
        self._by_key = {term.term_key: term for term in self.terms}

    # Lookups

    def knows(self, sport_key: str) -> bool:
        """Whether the term has been reviewed at all.

        False means nobody has looked at this term, NOT that it maps to nothing.
        A term that maps to nothing on purpose — Art, Playground, Special
        Olympics — is known, and knows() returns True for it.
        """
        return sport_key in self._by_key

    def term_for(self, sport_key: str) -> SportTerm | None:
        return self._by_key.get(sport_key)

    def vocab_for(self, sport_key: str) -> tuple[str, ...]:
        """The vocabulary sports this publisher term means.

        Empty for an unknown term and empty for a reviewed term that means no
        sport. Use knows() to tell those two apart; they are different facts and
        collapsing them is how an unreviewed term becomes invisible.
        """
        term = self._by_key.get(sport_key)

        return term.maps_to if term else ()

    # Whole-file views

    def rows(self) -> list[tuple[str, str]]:
        """Every (term_key, vocabulary sport) pair, in file order.

        This is the many-to-many link. One term may produce several pairs, which
        is the case a one-to-one alias dict cannot express: "Bike riding, BMX &
        cycling" produces a Cycling row and a BMX row, so a search for either
        sport finds the programme.
        """
        return [(term.term_key, sport) for term in self.terms for sport in term.maps_to]

    def added_sports(self) -> list[str]:
        """Vocabulary entries this crosswalk contributes rather than matches."""
        return [sport for term in self.terms if term.adds_to_vocabulary for sport in term.maps_to]

    def adaptive_sports(self) -> list[str]:
        """The adaptive and para sports held apart from their parents."""
        return [sport for term in self.terms if term.is_adaptive for sport in term.maps_to]

    def unknown_keys(self, sport_keys: list[str]) -> list[str]:
        """Which of these publisher keys are not in the reviewed file.

        Sorted and de-duplicated, because the caller reports one quarantine row
        per unreviewed TERM rather than one per programme carrying it.
        """
        return sorted({key for key in sport_keys if key not in self._by_key})

    # Checking

    def validate(self) -> None:
        """Check the file holds together. Raises rather than warning.

        A crosswalk that half loads is worse than one that does not load: the
        programmes would still be inserted and the sports would quietly be the
        subset that happened to parse.
        """
        vocabulary = set(self.venue_vocabulary)
        seen: set[str] = set()

        for term in self.terms:
            where = f"{term.term!r} ({term.term_key})"

            if term.relation not in RELATIONS:
                raise CrosswalkError(f"{where} has unknown relation {term.relation!r}")

            if term.term_key in seen:
                raise CrosswalkError(f"{where} appears more than once")

            seen.add(term.term_key)

            if not term.note.strip():
                raise CrosswalkError(
                    f"{where} carries no note. Every row in this file records a "
                    "reading, and a row with no reason is a row nobody checked."
                )

            if term.relation in UNTARGETED_RELATIONS:
                if term.maps_to:
                    raise CrosswalkError(
                        f"{where} is {term.relation} and must map to nothing, "
                        f"but maps to {list(term.maps_to)}"
                    )

                continue

            if not term.maps_to:
                raise CrosswalkError(
                    f"{where} is {term.relation} and maps to nothing. Use "
                    "not_a_sport or unmapped, so the emptiness is a decision."
                )

            if len(set(term.maps_to)) != len(term.maps_to):
                raise CrosswalkError(f"{where} maps to the same sport twice")

            for sport in term.maps_to:
                if term.relation in ADDED_RELATIONS:
                    if sport in vocabulary:
                        raise CrosswalkError(
                            f"{where} is {term.relation} but {sport!r} is already "
                            "in the venue vocabulary, so it is an alias and not "
                            "an addition"
                        )
                elif sport not in vocabulary:
                    raise CrosswalkError(
                        f"{where} maps to {sport!r}, which is not in the venue "
                        "vocabulary. Either the spelling is wrong or the row "
                        "should be added rather than aliased."
                    )

            # The rule the whole file exists for, enforced rather than trusted.
            if term.is_adaptive and term.maps_to != (term.term,):
                raise CrosswalkError(
                    f"{where} is an adaptive or para sport and must map to "
                    f"itself and nothing else, but maps to {list(term.maps_to)}. "
                    "Folding an adaptive sport into a non-adaptive parent is the "
                    "one change this crosswalk exists to refuse."
                )


def _term_from(raw: dict[str, Any]) -> SportTerm:
    return SportTerm(
        term=str(raw["term"]),
        term_key=str(raw["term_key"]),
        publisher_slug=str(raw["publisher_slug"]),
        publisher_term_id=int(raw["publisher_term_id"]),
        activity_count=int(raw["activity_count"]),
        relation=str(raw["relation"]),
        maps_to=tuple(raw.get("maps_to") or ()),
        note=str(raw.get("note") or ""),
    )


def load(path: Path | str | None = None) -> SportCrosswalk:
    """Read and check the reviewed crosswalk.

    Not cached. It is read once per load run, the file is 30 kB, and a cache
    that outlives an edit is a worse problem than the read.
    """
    source = Path(path) if path is not None else CROSSWALK_PATH

    document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}

    terms = [_term_from(raw) for raw in document.get("terms") or []]

    if not terms:
        raise CrosswalkError(
            f"{source} holds no terms. An empty crosswalk is not an empty "
            "taxonomy: it would make every publisher term look unreviewed and "
            "quarantine the lot."
        )

    crosswalk = SportCrosswalk(
        terms=terms,
        venue_vocabulary=list(document.get("venue_vocabulary") or []),
        metadata={key: value for key, value in document.items() if key not in {"terms"}},
    )

    crosswalk.validate()

    return crosswalk
