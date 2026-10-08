"""
tests/test_ds09_sport_crosswalk.py

The reviewed sport crosswalk, and what the transformer does with it.

WHAT THESE TESTS ARE PROTECTING
    A crosswalk is a file of judgements, and a file of judgements rots quietly:
    somebody adds a term without a reason, somebody points an adaptive sport at
    its non-adaptive parent to tidy up a search result, somebody regenerates the
    SQL and not the YAML. None of that breaks a build on its own. These tests
    make each of them break a build.

No network and no database. The crosswalk is a file, the migration is a file,
and the transformer is a pure function of its arguments.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from ingestion.crosswalks import sport
from ingestion.transformers import ds09_aaaplay as ds09

MIGRATION = Path(__file__).resolve().parents[1] / "sql" / "012_sport_crosswalk.sql"

# The backend's runtime alias dict, copied here as a LITERAL rather than
# imported. backend/ is a separate uv project with its own lock file and is not
# on this test's import path, and reaching across would couple the data CI job
# to the API's dependencies. Copied from backend/app/repositories/postgres.py,
# SPORT_ALIASES. If that dict changes, this test fails and the two are made to
# agree deliberately — which is the whole point of writing it down twice.
BACKEND_SPORT_ALIASES = {
    "football (soccer)": "soccer",
    "afl": "australian rules football",
    "tenpin bowling": "ten pin bowling",
    "bowls": "lawn bowls",
    "gym": "fitness / gymnasium workouts",
    "general fitness": "fitness / gymnasium workouts",
    "bike riding, bmx & cycling": "cycling",
}


@pytest.fixture(scope="module")
def crosswalk() -> sport.SportCrosswalk:
    return sport.load()


# The file itself


def test_the_reviewed_file_loads_and_holds_together(crosswalk: sport.SportCrosswalk) -> None:
    # load() calls validate(), so reaching here means every relation is known,
    # every row carries a note, every alias target is really in the vocabulary
    # and every added target really is not.
    assert len(crosswalk.terms) == 82
    assert len(crosswalk.venue_vocabulary) == 80


def test_every_term_key_is_what_the_transformer_would_produce(
    crosswalk: sport.SportCrosswalk,
) -> None:
    """The join key must be derived exactly as program_sport.sport_key is.

    This is the single most load-bearing fact in the file. If the key here is
    built by any other rule, every row still looks correct and nothing ever
    joins.
    """
    for term in crosswalk.terms:
        assert term.term_key == ds09._slug_key(term.term), term.term


def test_term_keys_agree_with_the_publisher_slugs(crosswalk: sport.SportCrosswalk) -> None:
    """A second, independent check on the same key, from the publisher's side."""
    for term in crosswalk.terms:
        assert term.term_key == term.publisher_slug.replace("-", "_"), term.term


def test_html_entities_are_decoded_in_the_file(crosswalk: sport.SportCrosswalk) -> None:
    """The API publishes '&amp;'; nothing in this file may still carry it.

    An entity left in `term` would leave it in the key, and the key is what
    program_sport joins on, so the mapping would silently never match.
    """
    for term in crosswalk.terms:
        assert "&amp;" not in term.term
        assert "&" not in term.term_key

    ampersands = {term.term for term in crosswalk.terms if "&" in term.term}

    assert ampersands == {"Bike riding, BMX & cycling", "Billiards, snooker & pool"}


def test_every_row_records_a_reason(crosswalk: sport.SportCrosswalk) -> None:
    for term in crosswalk.terms:
        assert len(term.note.strip()) > 20, term.term


# The judgement the crosswalk exists for


def test_adaptive_sports_are_never_folded_into_a_parent(
    crosswalk: sport.SportCrosswalk,
) -> None:
    """Boccia is not Bowls. Adaptive climbing is not Bouldering.

    Each adaptive term maps to itself and to nothing else. Any row pointing one
    of them at a non-adaptive sport fails here and, if it reached the database,
    fails a CHECK constraint in migration 012 as well.
    """
    adaptive = {term.term_key: term for term in crosswalk.terms if term.is_adaptive}

    assert set(adaptive) == {
        "adaptive_climbing",
        "boccia",
        "floor_curling",
        "goalball",
        "walking_and_rolling",
    }

    for term in adaptive.values():
        assert term.maps_to == (term.term,), term.term
        assert term.adds_to_vocabulary


@pytest.mark.parametrize(
    ("term_key", "forbidden"),
    [
        # The three mistakes a fuzzy matcher makes on this taxonomy, named.
        ("boccia", "Bocce"),
        ("boccia", "Lawn Bowls"),
        ("boccia", "Carpet Bowls"),
        ("adaptive_climbing", "Rock Climbing / Abseiling (Indoor)"),
        # "rolling" is the wheelchair. Folding it into walking deletes the word.
        ("walking_and_rolling", "Bushwalking, hiking or walking"),
    ],
)
def test_an_adaptive_sport_never_points_at_its_parent(
    crosswalk: sport.SportCrosswalk, term_key: str, forbidden: str
) -> None:
    assert forbidden not in crosswalk.vocab_for(term_key)


def test_the_validator_refuses_a_folded_adaptive_sport() -> None:
    """The rule is enforced, not merely documented."""
    folded = sport.SportCrosswalk(
        terms=[
            sport.SportTerm(
                term="Boccia",
                term_key="boccia",
                publisher_slug="boccia",
                publisher_term_id=1277,
                activity_count=4,
                relation="added_adaptive",
                maps_to=("Lawn Bowls",),
                note="Tidier this way.",
            )
        ],
        venue_vocabulary=["Lawn Bowls"],
    )

    with pytest.raises(sport.CrosswalkError, match="adaptive"):
        folded.validate()


def test_the_validator_refuses_a_row_with_no_reason() -> None:
    silent = sport.SportCrosswalk(
        terms=[
            sport.SportTerm(
                term="Archery",
                term_key="archery",
                publisher_slug="archery",
                publisher_term_id=1312,
                activity_count=1,
                relation="exact",
                maps_to=("Archery",),
                note="   ",
            )
        ],
        venue_vocabulary=["Archery"],
    )

    with pytest.raises(sport.CrosswalkError, match="no note"):
        silent.validate()


def test_the_validator_refuses_an_alias_to_a_sport_that_is_not_in_the_vocabulary() -> None:
    typo = sport.SportCrosswalk(
        terms=[
            sport.SportTerm(
                term="Calisthenics",
                term_key="calisthenics",
                publisher_slug="calisthenics",
                publisher_term_id=1340,
                activity_count=3,
                relation="alias",
                maps_to=("Calisthenics",),
                note="Spelled the publisher's way, which the venue register is not.",
            )
        ],
        venue_vocabulary=["Callisthenics"],
        # The one-l against two-l spelling is exactly the trap this catches.
    )

    with pytest.raises(sport.CrosswalkError, match="not in the venue vocabulary"):
        typo.validate()


# Many-to-many


def test_a_compound_term_reaches_both_of_its_sports(crosswalk: sport.SportCrosswalk) -> None:
    """The case the backend's one-to-one alias dict silently loses."""
    assert crosswalk.vocab_for("bike_riding_bmx_cycling") == ("Cycling", "BMX")


def test_a_term_the_vocabulary_splits_reaches_both_entries(
    crosswalk: sport.SportCrosswalk,
) -> None:
    """There is no unqualified tennis entry, so one of them is not a choice."""
    assert set(crosswalk.vocab_for("tennis")) == {"Tennis (Indoor)", "Tennis (Outdoor)"}


def test_rows_are_the_many_to_many_link(crosswalk: sport.SportCrosswalk) -> None:
    rows = crosswalk.rows()

    # 82 terms, 6 of which map to nothing on purpose, and two of which map to
    # two sports each.
    assert len(rows) == 78
    assert ("bike_riding_bmx_cycling", "BMX") in rows
    assert ("bike_riding_bmx_cycling", "Cycling") in rows

    # Several publisher terms reaching one vocabulary sport is the other
    # direction of the same link, and it has to work too.
    to_gym = sorted(key for key, sport_name in rows if sport_name == "Fitness / Gymnasium Workouts")

    assert to_gym == ["general_fitness", "gym", "weightlifting"]


# Terms that map to nothing


def test_terms_that_are_not_sports_are_reviewed_and_empty(
    crosswalk: sport.SportCrosswalk,
) -> None:
    """Empty is a decision here, and knows() has to tell it from a gap."""
    not_sports = {term.term_key for term in crosswalk.terms if term.relation == "not_a_sport"}

    assert not_sports == {
        "art",
        "camps",
        "circus",
        "performing_arts",
        "playground",
        "special_olympics",
    }

    for key in not_sports:
        assert crosswalk.knows(key)
        assert crosswalk.vocab_for(key) == ()


def test_an_unreviewed_term_is_not_the_same_as_a_term_that_means_no_sport(
    crosswalk: sport.SportCrosswalk,
) -> None:
    assert crosswalk.knows("art") is True
    assert crosswalk.knows("pickleball_but_spelled_wrong") is False
    assert crosswalk.unknown_keys(["art", "boccia", "quidditch"]) == ["quidditch"]


def test_added_sports_are_absent_from_the_venue_vocabulary(
    crosswalk: sport.SportCrosswalk,
) -> None:
    """An added sport that is already in the vocabulary is a mislabelled alias."""
    vocabulary = set(crosswalk.venue_vocabulary)

    added = crosswalk.added_sports()

    assert len(added) == 20
    assert not vocabulary.intersection(added)


# Agreement with the backend and with the migration


def test_every_backend_alias_is_reproduced_here(crosswalk: sport.SportCrosswalk) -> None:
    """This file complements SPORT_ALIASES; it must not contradict it.

    Each of the backend's seven entries has to appear in the crosswalk with the
    same target, so the query-time alias and the data-layer mapping cannot
    disagree about what a term means. The crosswalk may add targets the dict
    cannot express — 'Bike riding, BMX & cycling' also reaching BMX — but it may
    never drop one the dict has.
    """
    by_label = {term.term.lower(): term for term in crosswalk.terms}

    for label, expected in BACKEND_SPORT_ALIASES.items():
        assert label in by_label, f"{label!r} is in SPORT_ALIASES and not in the crosswalk"

        targets = {target.lower() for target in by_label[label].maps_to}

        assert expected in targets, f"{label!r} maps to {targets} and SPORT_ALIASES says {expected}"


_LITERAL = re.compile(r"'((?:[^']|'')*)'")


def _sql_text(literals: list[str]) -> str:
    """Join adjacent SQL string constants the way PostgreSQL does.

    Long notes are wrapped across several quoted literals, which the server
    concatenates. Reconstructing them here checks the wrapping did not eat a
    space or drop a doubled quote — a failure that would otherwise only show up
    as slightly wrong prose in a production table nobody reads.
    """
    return "".join(part.replace("''", "'") for part in literals)


def _migration_rows() -> set[tuple[str, str, str | None, str]]:
    """Pull every seeded row out of migration 012.

    Parsed rather than executed because the data CI job has no database. The
    point is not to prove the SQL runs, it is to prove the SQL and the YAML say
    the same thing — which is the failure mode of a generated file that somebody
    regenerates from a stale source.
    """
    text = MIGRATION.read_text(encoding="utf-8")

    body = text.split("VALUES\n", 1)[1].split("\n\n--", 1)[0]

    rows: set[tuple[str, str, str | None, str]] = set()

    for row in re.findall(r"\(\s*'DS-09',(.*?)\)[,;]\n", body, re.DOTALL):
        head, _, note_block = row.partition(",\n        ")

        literals = _LITERAL.findall(head)

        # term_key, term, publisher_slug, relation, then the target — which is
        # absent from this list when the row says NULL, which is exactly how a
        # term that means no sport is told apart from one that means a sport.
        # The unquoted term id and boolean between them are skipped by findall.
        key, _term, _slug, relation = literals[:4]
        target = literals[4].replace("''", "'") if len(literals) > 4 else None

        rows.add((key, relation, target, _sql_text(_LITERAL.findall(note_block))))

    return rows


def test_the_migration_and_the_reviewed_file_say_the_same_thing(
    crosswalk: sport.SportCrosswalk,
) -> None:
    expected: set[tuple[str, str, str | None, str]] = set()

    for term in crosswalk.terms:
        for target in term.maps_to or (None,):
            expected.add((term.term_key, term.relation, target, term.note))

    rows = _migration_rows()

    # 78 term-to-sport rows plus the 6 terms that mean no sport.
    assert len(rows) == 84
    assert rows == expected


def test_the_migration_enforces_the_adaptive_rule_in_the_database() -> None:
    """A constraint, not a comment. Someone has to delete it to break the rule."""
    text = MIGRATION.read_text(encoding="utf-8")

    assert "sport_crosswalk_adaptive_is_never_folded" in text
    assert "relation <> 'added_adaptive' OR vocab_sport = term" in text

    # The gap view is what makes an unreviewed term visible from the database
    # side, and the LEFT JOIN is what stops the resolved view deleting it.
    assert "CREATE VIEW public.sport_crosswalk_gap" in text
    assert "LEFT JOIN public.sport_crosswalk cw" in text


# What the transformer does with it


def _activity(activity_id: int, type_ids: list[int]) -> dict[str, object]:
    return {
        "id": activity_id,
        "title": {"rendered": f"Programme {activity_id}"},
        "link": f"https://aaaplay.org.au/activity/{activity_id}/",
        "activity_type": type_ids,
        "acf": {"activity_latitude": -37.81, "activity_longitude": 144.96},
    }


TAXONOMY = {
    "activity_type": [
        {"id": 1277, "name": "Boccia"},
        {"id": 1333, "name": "Bike riding, BMX &amp; cycling"},
        {"id": 9001, "name": "Quidditch"},
    ]
}


def test_the_transformer_decodes_the_entity_into_the_key_and_the_label() -> None:
    result = ds09.transform(
        activities=[_activity(1, [1333])],
        facilities=[],
        taxonomy_terms=TAXONOMY,
    )

    row = result.program_sports.iloc[0]

    assert row["sport_label"] == "Bike riding, BMX & cycling"
    assert row["sport_key"] == "bike_riding_bmx_cycling"


def test_a_programme_keeps_every_sport_it_carries() -> None:
    """program_sport is keyed (program_id, sport_key); 52 activities need this."""
    result = ds09.transform(
        activities=[_activity(1, [1277, 1333])],
        facilities=[],
        taxonomy_terms=TAXONOMY,
    )

    assert set(result.program_sports["sport_key"]) == {"boccia", "bike_riding_bmx_cycling"}


def test_an_unreviewed_term_is_quarantined_and_the_programme_still_loads(
    crosswalk: sport.SportCrosswalk,
) -> None:
    """Visible, not dropped — and the programme is not punished for it."""
    result = ds09.transform(
        activities=[_activity(1, [9001]), _activity(2, [9001]), _activity(3, [1277])],
        facilities=[],
        taxonomy_terms=TAXONOMY,
        sport_crosswalk=crosswalk,
    )

    assert len(result.programs) == 3
    assert len(result.program_sports) == 3

    quarantine = result.quarantine

    assert list(quarantine["reason"]) == ["SCHEMA_VIOLATION"]
    assert list(quarantine["natural_key"]) == ["activity_type:quidditch"]
    # One row per unreviewed TERM, carrying how many programmes it cost.
    assert quarantine.iloc[0]["payload"]["programs_affected"] == 2

    assert result.stats["sport_terms_unreviewed"] == 1
    assert result.stats["sport_terms_unreviewed_keys"] == ["quidditch"]


def test_a_reviewed_term_that_means_no_sport_is_not_quarantined(
    crosswalk: sport.SportCrosswalk,
) -> None:
    result = ds09.transform(
        activities=[_activity(1, [1358])],
        facilities=[],
        taxonomy_terms={"activity_type": [{"id": 1358, "name": "Art"}]},
        sport_crosswalk=crosswalk,
    )

    assert result.quarantine.empty
    assert result.stats["sport_terms_unreviewed"] == 0


def test_without_a_crosswalk_the_check_reports_that_it_did_not_run() -> None:
    """Never zero. Zero would read as 'checked and found nothing'."""
    result = ds09.transform(
        activities=[_activity(1, [9001])],
        facilities=[],
        taxonomy_terms=TAXONOMY,
    )

    assert result.stats["sport_terms_unreviewed"] is None
    assert result.quarantine.empty
    assert "crosswalk not supplied" in result.summary()
