"""The event SQL against the crosswalk migration, read by name.

NO DATABASE. tests/integration is empty and the unit tests run against the
in-memory FakeRepository, so nothing in this suite executes the SQL in
repositories/postgres.py. That is how the API came to resolve event sports
through a seven-entry dict while migration 012 held eighty-four reviewed rows
built for exactly that job, for a whole iteration, with every test green.

These tests are the substitute for the type checker the SQL does not have.
They cannot prove a query returns the right rows -- only a database can do that
-- but they can prove the query names columns that exist, and that the
crosswalk is being asked rather than guessed at. Both failures are silent in
production: a renamed column is an error at request time, and a query that
stops using the view is not an error at all, just wrong answers.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
POSTGRES_PY = REPO_ROOT / "backend" / "app" / "repositories" / "postgres.py"
MIGRATION = REPO_ROOT / "data" / "sql" / "012_sport_crosswalk.sql"

SQL = POSTGRES_PY.read_text(encoding="utf-8")
CROSSWALK_SQL = MIGRATION.read_text(encoding="utf-8")

# The columns the view publishes, from the CREATE VIEW in 012.
VIEW_COLUMNS = {
    "program_id",
    "sport_key",
    "sport_label",
    "vocab_sport",
    "relation",
    "adds_to_vocabulary",
    "unreviewed",
}


def test_the_view_still_publishes_the_columns_the_api_reads() -> None:
    """Guards against a rename in 012 that the API would not notice."""
    body = CROSSWALK_SQL.split("CREATE VIEW public.program_sport_vocabulary AS", 1)[1]
    body = body.split(";", 1)[0]

    for column in VIEW_COLUMNS:
        assert column in body, f"{column} is not in the program_sport_vocabulary view"


def test_every_psv_column_the_api_reads_exists_in_the_view() -> None:
    """The API's own references, checked against that list.

    Catches `psv.sport_name` or `psv.is_adaptive` -- a plausible-looking column
    that does not exist and fails only when a request reaches it.
    """
    referenced = set(re.findall(r"psv\.(\w+)", SQL))

    assert referenced, "expected the repository to read the crosswalk view"
    unknown = referenced - VIEW_COLUMNS
    assert not unknown, f"read from program_sport_vocabulary but not in it: {unknown}"


def test_programme_sports_are_read_through_the_crosswalk() -> None:
    """program_sport is the raw table; the view is the reviewed answer.

    A query that joins program_sport directly has skipped the review, which is
    the defect this whole file exists to catch.
    """
    for name in ("SQL_EVENT_SPORTS", "SQL_SPORTS"):
        query = _named_query(name)
        assert "program_sport_vocabulary" in query, f"{name} does not use the crosswalk view"

        direct = re.search(r"\bprogram_sport\b(?!_vocabulary)", query)
        assert direct is None, f"{name} reads program_sport directly, bypassing the crosswalk"


def test_the_hardcoded_alias_dict_is_gone() -> None:
    """The seven-entry map the crosswalk replaces.

    It could express neither a term naming two sports (Tennis, which is both
    the indoor and the outdoor vocabulary entry) nor a sport no venue records
    (Boccia), and it silently covered seven of twenty-five terms.
    """
    assert "SPORT_ALIASES" not in SQL
    assert "_ALIASES_JSON" not in SQL
    assert "aliases" not in SQL


def test_not_a_sport_terms_are_kept_out_of_the_sport_labels() -> None:
    """Art, Playground and Special Olympics are not sports.

    The crosswalk records that decision; the event card must honour it rather
    than print them beside Basketball.
    """
    assert "not_a_sport" in _named_query("EVENT_FROM")


def test_the_events_filter_matches_every_vocabulary_sport_not_just_one() -> None:
    """A Tennis programme answers both Tennis (Indoor) and Tennis (Outdoor).

    The card shows one name, so a filter written against that single name would
    drop half the split terms.
    """
    events = _named_query("SQL_EVENTS")
    assert "unnest(sp.vocabs)" in events, "the sport filter must consider every mapped sport"


def _named_query(name: str) -> str:
    """The text of one module-level SQL constant."""
    match = re.search(rf'^{name} = f?"""(.*?)"""', SQL, re.DOTALL | re.MULTILINE)
    assert match, f"{name} not found in {POSTGRES_PY.name}"
    return match.group(1)
