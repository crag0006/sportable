"""The legend cannot drift from the enum it explains (US3.1).

AC3.1.1 says the legend explains every icon and colour used on the map. That is
a promise until something fails when it stops being true, which is what this
module is for. Three things have to agree:

    1. the ``amenity_kind`` enum in data/sql/001_schema.sql — the marker types
       that can exist at all;
    2. the ``facility_legend`` view in data/sql/011_vocabulary_and_summary.sql —
       the record the serving store holds;
    3. ``app.domain.legend.LEGEND`` — the record the API serves.

The SQL is read off disk rather than out of a database, because the unit suite
runs with no network and no PostGIS (see tests/unit/conftest.py) and because
the failure being guarded against is somebody editing one file and not the
other — which is visible in the files themselves.
"""

import re
from itertools import pairwise
from pathlib import Path

import pytest
from app.domain.facilities import KIND_LABELS, KINDS
from app.domain.legend import LEGEND, screen_reader_summary
from fastapi.testclient import TestClient

# backend/tests/unit/test_legend.py -> the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_SQL = REPO_ROOT / "data" / "sql" / "001_schema.sql"
LEGEND_SQL = REPO_ROOT / "data" / "sql" / "011_vocabulary_and_summary.sql"

# The seven columns of one VALUES row in the view, in declaration order.
LEGEND_COLUMNS = (
    "kind",
    "display_label",
    "shape",
    "colour_token",
    "colour_hex",
    "description",
    "screen_reader_text",
)


def _without_comments(sql: str) -> str:
    """Drop ``--`` line comments so an apostrophe in prose cannot look like SQL.

    Walked rather than regexed because a CSS custom property is spelled
    ``'--facility-toilet'`` — a perfectly good string literal that begins with
    what looks like the start of a comment.
    """
    out: list[str] = []
    in_string = False
    i = 0
    while i < len(sql):
        char = sql[i]
        if in_string:
            out.append(char)
            if char == "'":
                # '' inside a literal is an escaped quote, not the end of one.
                if sql[i + 1 : i + 2] == "'":
                    out.append("'")
                    i += 1
                else:
                    in_string = False
        elif char == "'":
            in_string = True
            out.append(char)
        elif char == "-" and sql[i + 1 : i + 2] == "-":
            while i < len(sql) and sql[i] != "\n":
                i += 1
            continue
        else:
            out.append(char)
        i += 1
    return "".join(out)


def _enum_values(name: str) -> list[str]:
    sql = _without_comments(SCHEMA_SQL.read_text())
    match = re.search(rf"CREATE TYPE (?:public\.)?{name} AS ENUM\s*\((.*?)\);", sql, re.S)
    assert match is not None, f"{name} is no longer declared in {SCHEMA_SQL.name}"
    return re.findall(r"'([^']+)'", match.group(1))


def _legend_view_rows() -> list[dict[str, str]]:
    """The literal rows of the ``facility_legend`` view, as dictionaries."""
    sql = _without_comments(LEGEND_SQL.read_text())
    match = re.search(r"LEFT JOIN \(\s*VALUES(.*?)\) AS v \(", sql, re.S)
    assert match is not None, "the facility_legend VALUES block has moved or been renamed"
    literals = re.findall(r"'((?:[^']|'')*)'", match.group(1))
    width = len(LEGEND_COLUMNS)
    assert len(literals) % width == 0, (
        f"expected rows of {width} values, found {len(literals)} literals"
    )
    return [
        dict(zip(LEGEND_COLUMNS, literals[i : i + width], strict=True))
        for i in range(0, len(literals), width)
    ]


# -------------------------------------------------- the divergence guard
def test_every_amenity_kind_has_a_legend_entry():
    """AC3.1.1. Add a marker type without explaining it and this fails.

    Order matters as well as membership: the legend is read alongside the four
    facility tiles, which are drawn in enum order.
    """
    assert [entry.kind for entry in LEGEND] == _enum_values("amenity_kind")


def test_legend_view_matches_the_served_legend():
    """The SQL view and the API's copy are the same record, field for field."""
    rows = _legend_view_rows()
    assert len(rows) == len(LEGEND)
    for row, entry in zip(rows, LEGEND, strict=True):
        assert row["kind"] == entry.kind
        assert row["display_label"] == entry.display_label
        assert row["shape"] == entry.shape
        assert row["colour_token"] == entry.colour_token
        assert row["colour_hex"] == entry.colour_hex
        assert row["description"] == entry.description
        assert row["screen_reader_text"] == entry.screen_reader_text


def test_legend_view_is_driven_by_the_enum():
    """The view unnests the enum rather than listing the kinds.

    This is the mechanism behind the guarantee: a kind added to the enum and
    not to the VALUES block shows up in the view as a row with a NULL label,
    loudly, instead of quietly not existing.
    """
    sql = LEGEND_SQL.read_text()
    assert "unnest(enum_range(NULL::public.amenity_kind))" in sql
    assert "LEFT JOIN" in sql


def test_labels_are_the_same_words_as_the_facility_tiles():
    """One spelling per facility, product-wide. No second vocabulary."""
    assert {e.kind: e.display_label for e in LEGEND} == {k: KIND_LABELS[k] for k in KINDS}


# ----------------------------------------------- the three channels (AC3.1.2)
def test_each_type_has_a_distinct_shape_colour_and_label():
    shapes = [e.shape for e in LEGEND]
    colours = [e.colour_hex for e in LEGEND]
    labels = [e.display_label for e in LEGEND]
    assert len(set(shapes)) == len(shapes), f"two marker types share a shape: {shapes}"
    assert len(set(colours)) == len(colours), f"two marker types share a colour: {colours}"
    assert len(set(labels)) == len(labels), f"two marker types share a label: {labels}"


def _relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance — what the colour becomes in greyscale."""
    raw = hex_colour.lstrip("#")
    channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def test_markers_survive_desaturation():
    """AC3.1.3.

    Shape is the primary channel and carries this on its own — the test above
    is the one that matters. This checks the redundant channel has not been
    allowed to collapse as well: four fills that all desaturate to the same
    grey would make a greyscale map noisier than it needs to be even with
    distinct outlines.
    """
    luminances = sorted(_relative_luminance(e.colour_hex) for e in LEGEND)
    gaps = [b - a for a, b in pairwise(luminances)]
    assert min(gaps) >= 0.10, f"legend colours converge in greyscale: {luminances}"


# ---------------------------------------------------------- the endpoint
def test_facility_types_endpoint_serves_the_whole_legend(client: TestClient):
    body = client.get("/api/v1/facility-types").json()
    served = body["facility_types"]
    assert [row["type"] for row in served] == list(KINDS)
    for row in served:
        assert row["shape"] in ("circle", "square", "triangle", "diamond")
        assert row["colour_token"].startswith("--")
        assert re.fullmatch(r"#[0-9A-F]{6}", row["colour_hex"])
        assert row["description"] and row["screen_reader_text"]


def test_spoken_legend_comes_from_the_same_rows_as_the_drawn_one(client: TestClient):
    """AC3.1.4. The spoken legend cannot describe a marker the map does not draw."""
    body = client.get("/api/v1/facility-types").json()
    spoken = body["screen_reader_summary"]
    for row in body["facility_types"]:
        assert row["screen_reader_text"] in spoken
    assert spoken == screen_reader_summary()
    # And it says the shapes are there on purpose, rather than leaving a
    # greyscale reader to work it out.
    assert "shape" in body["note"]


@pytest.mark.parametrize("entry", LEGEND, ids=[e.kind for e in LEGEND])
def test_spoken_text_names_the_shape(entry):
    """Shape first, because shape is what the listener is told to look for."""
    assert entry.shape in entry.screen_reader_text
    assert entry.display_label in entry.screen_reader_text
