"""Tests for derive/place_geography.py and migration 010.

NO DATABASE AND NO NETWORK. The containment test itself belongs to PostGIS and
is not re-implemented here to be mocked; what is tested is everything around it
that a wrong answer could hide in:

*   the rules that are pure Python — name normalisation, the agreement rate, and
    when a rate is low enough to want a person;
*   the report, because a quality figure that reads well when it is fine and
    says nothing when it is not is worse than no figure;
*   the SQL against the migration, by name. There is no database in CI, so a
    column renamed in 010 and not in the module would otherwise be found at
    3 a.m. by whoever runs the pipeline. These tests are the substitute for the
    type checker the SQL does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

from derive import place_geography as pg

DATA_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = DATA_ROOT / "sql" / "010_program_venue_geography.sql"

# Columns 010 adds to program_venue. The module may write these and nothing else.
DERIVED_COLUMNS = {
    "derived_suburb_code",
    "derived_suburb_name",
    "derived_postcode",
    "derived_at",
}


def _outcome(**overrides: object) -> pg.GeographyOutcome:
    """An outcome with the real DS-09 shape, which individual tests bend."""
    values: dict[str, object] = {
        "rows_derived": 552,
        "places": 552,
        "geocoded": 552,
        "attempted": 552,
        "suburb_derived": 552,
        "postcode_derived": 552,
        "pair_derived": 552,
        "pair_published": 288,
        "geocoded_without_pair": 0,
        "suburb_comparable": 288,
        "suburb_agreed": 285,
        "postcode_comparable": 288,
        "postcode_agreed": 286,
    }
    values.update(overrides)
    return pg.GeographyOutcome(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- names


def test_abs_suffix_is_stripped_so_preston_matches_preston_vic() -> None:
    assert pg.normalise_suburb_name("Preston (Vic.)") == "preston"
    assert pg.normalise_suburb_name("Preston") == "preston"


def test_nested_abs_suffix_is_stripped() -> None:
    # The ABS disambiguates twice over for localities that repeat inside a state.
    assert pg.normalise_suburb_name("Melton (Melton - Vic.)") == "melton"


def test_case_and_surrounding_space_do_not_make_a_disagreement() -> None:
    assert pg.normalise_suburb_name("  ST KILDA  ") == "st kilda"


def test_absent_name_normalises_to_absent_and_not_to_empty_string() -> None:
    # "" would compare equal to another "" and manufacture an agreement between
    # two rows that said nothing.
    assert pg.normalise_suburb_name(None) is None


def test_internal_brackets_are_left_alone() -> None:
    # Only a trailing bracket is the ABS suffix; anything else is part of a name
    # and removing it would silently rename the suburb.
    assert pg.normalise_suburb_name("Kings (Park) Estate Road") == "kings (park) estate road"


# ------------------------------------------------------------------ agreement


def test_agreement_rate_is_the_share_of_comparable_rows() -> None:
    assert pg.agreement_rate(285, 288) == 285 / 288


def test_agreement_rate_is_unknown_when_nothing_is_comparable() -> None:
    # Not 1.0. An empty set agrees with nothing, and reporting 100% here would
    # be the invented positive the pipeline exists to avoid.
    assert pg.agreement_rate(0, 0) is None
    assert pg.agreement_rate(0, -1) is None


def test_review_is_wanted_below_the_floor_and_not_at_it() -> None:
    assert pg.needs_review(0.90) is True
    assert pg.needs_review(pg.AGREEMENT_FLOOR) is False
    assert pg.needs_review(1.0) is False


def test_an_unknown_rate_does_not_raise_an_alarm() -> None:
    # An empty database is not a quality incident.
    assert pg.needs_review(None) is False


def test_outcome_exposes_both_rates_and_the_review_flag() -> None:
    outcome = _outcome(suburb_agreed=200, suburb_comparable=288)
    assert outcome.suburb_agreement == 200 / 288
    assert outcome.postcode_agreement == 286 / 288
    assert outcome.wants_review is True


# --------------------------------------------------------------------- report


def test_summary_reports_both_agreement_rates() -> None:
    text = _outcome().summary()
    assert "285/288" in text
    assert "286/288" in text
    assert "99.0%" in text  # 285/288, to one decimal
    assert "99.3%" in text  # 286/288


def test_summary_says_not_comparable_rather_than_a_number_it_does_not_have() -> None:
    text = _outcome(suburb_comparable=0, suburb_agreed=0).summary()
    assert "not comparable" in text


def test_summary_shows_the_reach_the_derivation_bought() -> None:
    # The whole point of D4: 288 published pairs, 552 after deriving.
    assert "288 -> 552" in _outcome().summary()


def test_summary_names_places_the_boundary_layers_could_not_place() -> None:
    text = _outcome(pair_derived=540, geocoded_without_pair=12).summary()
    assert "STILL UNREACHABLE" in text
    assert "12" in text


def test_summary_stays_quiet_when_every_geocoded_place_was_placed() -> None:
    assert "STILL UNREACHABLE" not in _outcome().summary()


def test_summary_shouts_when_the_publisher_and_the_geocode_disagree_often() -> None:
    text = _outcome(postcode_agreed=200, postcode_comparable=288).summary()
    assert "BELOW THE 95% FLOOR" in text


def test_summary_does_not_shout_on_a_healthy_run() -> None:
    assert "BELOW THE" not in _outcome().summary()


def test_disagreement_listing_says_so_when_there_is_nothing_to_list() -> None:
    # An empty list must read as "they agree", never as an empty report block
    # that looks like the check did not run.
    assert "no disagreements" in pg._format_disagreements([])


def test_disagreement_listing_prints_both_sides_for_a_human() -> None:
    text = pg._format_disagreements(
        [
            {
                "program_venue_id": "DS-09:place:1",
                "name": "Example Leisure Centre",
                "full_address": "1 Example St",
                "published_suburb": "Preston",
                "derived_suburb_name": "Reservoir (Vic.)",
                "published_postcode": "3072",
                "derived_postcode": "3073",
            }
        ]
    )
    assert "Preston" in text
    assert "Reservoir (Vic.)" in text
    assert "3072" in text
    assert "3073" in text


# ------------------------------------------------------- SQL against the schema


def _migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_the_migration_exists_where_the_module_says_it_does() -> None:
    assert MIGRATION.is_file()


def test_every_derived_column_the_module_touches_is_added_by_the_migration() -> None:
    sql = _migration_sql()
    used = set(re.findall(r"\bderived_\w+", pg.SQL_DERIVE + pg.SQL_COVERAGE + pg.SQL_AGREEMENT))

    assert used, "the derive statement stopped naming any derived column"

    for column in used:
        assert f"{column}" in sql, f"{column} is written by the module but not added by 010"


def test_the_module_writes_derived_columns_and_nothing_else() -> None:
    # The publisher's suburb_name, postcode and full_address are what a human
    # reads. A SET that reached them would be the one change this task must
    # never make, so it is asserted rather than trusted.
    set_clause = pg.SQL_DERIVE.split("SET", 1)[1].split("FROM", 1)[0]
    assigned = set(re.findall(r"(\w+)\s*=", set_clause))

    assert assigned == DERIVED_COLUMNS


def test_the_derive_statement_skips_rows_with_no_geocode() -> None:
    # No point, no containment test, and no derived_at either: the row has never
    # been tested and must keep saying so.
    assert "p.geom IS NOT NULL" in pg.SQL_DERIVE


def test_the_derive_statement_can_be_re_run_without_redoing_settled_rows() -> None:
    assert "only_new" in pg.SQL_DERIVE
    assert "p.derived_at IS NULL" in pg.SQL_DERIVE


def test_the_derive_statement_asserts_containment_and_not_nearness() -> None:
    # A nearest-polygon fallback would turn "no polygon contains this point"
    # into a value nobody published.
    assert "ST_Contains" in pg.SQL_DERIVE
    assert "ST_DWithin" not in pg.SQL_DERIVE
    assert "ST_Distance" not in pg.SQL_DERIVE


def test_the_objects_the_module_reads_are_created_by_the_migration() -> None:
    sql = _migration_sql()
    assert "CREATE VIEW public.program_venue_geography_check" in sql
    assert f"CREATE MATERIALIZED VIEW public.{pg.PLACE_VOCABULARY}" in sql
    assert "program_venue_geography_check" in pg.SQL_AGREEMENT
    assert "program_venue_geography_check" in pg.SQL_DISAGREEMENTS


def test_the_columns_the_disagreement_listing_selects_exist_in_the_view() -> None:
    sql = _migration_sql()
    # Bounded by the next statement rather than by the first semicolon: the
    # view body carries prose, and prose carries semicolons.
    view = sql.split("CREATE VIEW public.program_venue_geography_check", 1)[1].split(
        "COMMENT ON VIEW", 1
    )[0]

    for column in (
        "published_suburb",
        "derived_suburb_name",
        "published_postcode",
        "derived_postcode",
        "suburb_agrees",
        "postcode_agrees",
    ):
        assert column in view
        assert column in pg.SQL_DISAGREEMENTS + pg.SQL_AGREEMENT


def test_the_dropdown_view_keeps_the_column_names_the_api_already_returns() -> None:
    # PlaceRow is (suburb, postcode, venue_count). Keeping those names is what
    # makes the API change a FROM clause instead of a refactor.
    sql = _migration_sql()
    block = sql.split(f"CREATE MATERIALIZED VIEW public.{pg.PLACE_VOCABULARY}", 1)[1]

    for column in ("AS suburb", "AS postcode", "AS venue_count"):
        assert column in block


def test_the_dropdown_view_can_be_refreshed_without_blocking_the_api() -> None:
    # REFRESH ... CONCURRENTLY needs a unique index over plain column names.
    assert "CREATE UNIQUE INDEX place_vocabulary_pk_idx" in _migration_sql()


def test_the_migration_is_one_transaction_with_a_rollback_block() -> None:
    sql = _migration_sql()
    assert sql.count("BEGIN;") >= 1
    assert "COMMIT;" in sql
    assert "-- ROLLBACK" in sql


def test_the_rollback_block_undoes_everything_the_migration_creates() -> None:
    sql = _migration_sql()
    rollback = sql.split("-- ROLLBACK", 1)[1]

    assert "DROP MATERIALIZED VIEW IF EXISTS public.place_vocabulary" in rollback
    assert "DROP VIEW IF EXISTS public.program_venue_geography_check" in rollback

    for column in DERIVED_COLUMNS:
        assert f"DROP COLUMN IF EXISTS {column}" in rollback


def test_the_migration_records_absence_as_absence() -> None:
    # The constraint that keeps "never tested" and "tested, found nothing"
    # distinguishable. Losing it would make a NULL unreadable.
    assert "program_venue_derived_needs_a_run" in _migration_sql()


# ---------------------------------------------------- the glue, with a fake conn
#
# Not a mock of PostGIS — the containment test is the database's job. This is a
# stand-in for psycopg's connection, just large enough to prove that the module
# passes the parameters it says it does and reads the result columns back under
# the names the SQL gives them. A key renamed in one place and not the other is
# the failure mode these catch, and it is the one no linter can see.


class _FakeCursor:
    def __init__(self, result: dict[str, int] | list[dict[str, object]] | None) -> None:
        self._result = result
        self.rowcount = 264

    def fetchone(self) -> object:
        return self._result

    def fetchall(self) -> object:
        return self._result

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> _FakeCursor:
        return self


class _FakeConnection:
    """Answers each statement from a canned result, and remembers what it saw."""

    def __init__(self, results: dict[str, object], fail_concurrently: bool = False) -> None:
        self._results = results
        self.fail_concurrently = fail_concurrently
        self.statements: list[str] = []
        self.params: list[object] = []
        self.rolled_back = 0

    def execute(self, sql: str, params: object = None) -> _FakeCursor:
        self.statements.append(sql)
        self.params.append(params)

        for marker, result in self._results.items():
            if marker in sql:
                return _FakeCursor(result)  # type: ignore[arg-type]

        return _FakeCursor(None)

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(None)

    def rollback(self) -> None:
        self.rolled_back += 1


COVERAGE_ROW = {
    "places": 552,
    "geocoded": 552,
    "attempted": 552,
    "suburb_derived": 550,
    "postcode_derived": 549,
    "pair_derived": 548,
    "pair_published": 288,
    "geocoded_without_pair": 4,
}

AGREEMENT_ROW = {
    "suburb_comparable": 288,
    "suburb_agreed": 285,
    "postcode_comparable": 288,
    "postcode_agreed": 286,
}


def _conn() -> _FakeConnection:
    return _FakeConnection(
        {
            "UPDATE": None,
            "FROM program_venue\n": COVERAGE_ROW,
            "program_venue_geography_check": AGREEMENT_ROW,
        }
    )


def test_derive_only_touches_untested_rows_unless_told_otherwise() -> None:
    conn = _conn()
    assert pg.derive(conn) == 264
    assert conn.params[0] == {"only_new": True}

    pg.derive(conn, only_new=False)
    assert conn.params[1] == {"only_new": False}


def test_report_reads_every_count_back_under_the_name_the_sql_gave_it() -> None:
    outcome = pg.report(_conn(), rows_derived=264)

    assert outcome.places == 552
    assert outcome.pair_published == 288
    assert outcome.pair_derived == 548
    assert outcome.geocoded_without_pair == 4
    assert outcome.postcode_agreed == 286
    assert outcome.rows_derived == 264


def test_a_report_run_writes_nothing() -> None:
    conn = _conn()
    pg.report(conn)

    assert not any(s.strip().startswith("UPDATE") for s in conn.statements)


def test_the_first_refresh_after_the_migration_falls_back_to_a_blocking_one() -> None:
    # REFRESH ... CONCURRENTLY cannot run against a materialised view that has
    # never been populated, which is exactly the state 010 leaves it in.
    class _NeverPopulated(_FakeConnection):
        def cursor(self) -> _FakeCursor:
            if self.rolled_back == 0:
                raise RuntimeError("CONCURRENTLY requires a populated view")
            return _FakeCursor(None)

    conn = _NeverPopulated({})
    pg.refresh_place_vocabulary(conn)

    assert conn.rolled_back == 1
