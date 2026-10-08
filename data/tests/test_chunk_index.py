"""Integration test. Needs DATABASE_URL pointing at a database with migrations
001 to 013 applied, on an image that has pgvector. Everything runs inside one
transaction that is rolled back, so nothing persists."""

import hashlib
import os

import psycopg
import pytest
from derive.chunk_index import build_index
from derive.chunker import chunk_description
from psycopg.rows import dict_row

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set"),
]

MODEL = "test-model"


class FakeEmbedder:
    model_id = MODEL

    def __init__(self, fail_after: int | None = None):
        self.calls = 0
        self.fail_after = fail_after

    def embed(self, text):
        if self.fail_after is not None and self.calls >= self.fail_after:
            raise RuntimeError("bedrock down")
        self.calls += 1
        seed = hashlib.sha256(text.encode()).digest()
        return [seed[i % 32] / 255 for i in range(1024)]


LONG = " ".join(f"Sentence {i} tells you what to bring to the session." for i in range(30))
OTHER = " ".join(f"Different sentence {i} about carers being welcome." for i in range(30))


@pytest.fixture
def conn():
    connection = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def seeded(conn):
    conn.execute(
        """
        INSERT INTO source (source_id, name, publisher, licence_name, licence_url,
                            attribution_text, publisher_scope)
        VALUES ('DS-09', 't', 't', 't', 'https://example.com', 't', 'statewide')
        ON CONFLICT DO NOTHING
        """
    )
    run = conn.execute(
        """
        INSERT INTO load_run (source_id, dt_partition, raw_object_key, raw_sha256)
        VALUES ('DS-09', '2026-10-01', 'k', repeat('a', 64)) RETURNING load_run_id
        """
    ).fetchone()["load_run_id"]

    def add(program_id, description, n):
        conn.execute(
            """
            INSERT INTO program (program_id, source_id, load_run_id, publisher_key, name,
                                 description, geom, retrieved_at)
            VALUES (%s, 'DS-09', %s, %s, 'p', %s,
                    ST_SetSRID(ST_MakePoint(144.96, -37.81), 7844), now())
            """,
            (program_id, run, n, description),
        )

    add("TEST:1", LONG, 900001)
    add("TEST:2", OTHER, 900002)
    add("TEST:3", None, 900003)
    return conn


def _count(conn, program_id):
    return conn.execute(
        "SELECT count(*) AS n FROM program_description_chunk "
        "WHERE program_id = %s AND embedding_model_id = %s",
        (program_id, MODEL),
    ).fetchone()["n"]


def test_first_run_then_second_run_embeds_nothing(seeded):
    first = FakeEmbedder()
    build_index(seeded, first)
    assert first.calls > 0
    assert _count(seeded, "TEST:1") == len(chunk_description(LONG))
    assert _count(seeded, "TEST:3") == 0

    second = FakeEmbedder()
    outcome = build_index(seeded, second)
    assert second.calls == 0
    assert outcome.written == 0 and outcome.deleted == 0


def test_editing_one_description_embeds_only_what_changed(seeded):
    build_index(seeded, FakeEmbedder())

    new_text = LONG + " One brand new closing sentence about parking."
    seeded.execute("UPDATE program SET description = %s WHERE program_id = 'TEST:1'", (new_text,))

    embedder = FakeEmbedder()
    build_index(seeded, embedder)

    assert 0 < embedder.calls <= len(chunk_description(new_text))
    assert _count(seeded, "TEST:2") == len(chunk_description(OTHER))


def test_removed_text_removes_chunks(seeded):
    build_index(seeded, FakeEmbedder())
    seeded.execute("UPDATE program SET description = NULL WHERE program_id = 'TEST:2'")

    build_index(seeded, FakeEmbedder())
    assert _count(seeded, "TEST:2") == 0


def test_failed_embedding_leaves_previous_index_untouched(seeded):
    build_index(seeded, FakeEmbedder())
    seeded.execute(
        "UPDATE program SET description = %s WHERE program_id = 'TEST:1'",
        (LONG + " Changed ending.",),
    )

    with pytest.raises(RuntimeError):
        build_index(seeded, FakeEmbedder(fail_after=0))

    stored = seeded.execute(
        "SELECT string_agg(chunk_text, '') AS t FROM program_description_chunk "
        "WHERE program_id = 'TEST:1' AND embedding_model_id = %s",
        (MODEL,),
    ).fetchone()["t"]
    assert "Changed ending." not in stored


def test_every_chunk_traces_to_source_and_run(seeded):
    build_index(seeded, FakeEmbedder())
    orphans = seeded.execute(
        "SELECT count(*) AS n FROM program_description_chunk c "
        "JOIN program p USING (program_id) "
        "WHERE c.source_id <> p.source_id OR c.load_run_id <> p.load_run_id"
    ).fetchone()["n"]
    assert orphans == 0
