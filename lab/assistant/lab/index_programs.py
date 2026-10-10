"""Chunk every program description with the repository's chunker, embed on the
embedding server, and upsert into program_chunk in the VECTOR database. Rows
are tagged with EMBED_MODEL so they never mix with Titan rows.

    set EMBED_BASE=http://IP:PORT/v1
    set EMBED_MODEL=bge-m3
    uv run python -m lab.index_programs
"""

import sys
import time
from pathlib import Path

import psycopg

from lab import config
from lab.retrieval import embed, ensure_store, vector_literal, vector_store

REPO = Path(__file__).resolve().parents[2] / "sportable"
sys.path.insert(0, str(REPO / "data"))
from derive.chunker import chunk_description  # noqa: E402

SQL_PROGRAMS = """
SELECT program_id, source_id, load_run_id, description
  FROM program
 WHERE description IS NOT NULL AND length(description) > 40
 ORDER BY program_id
"""

SQL_UPSERT = """
INSERT INTO program_chunk
       (program_id, chunk_index, chunk_text, char_start, char_end, content_sha256,
        embedding, embedding_model_id, source_id, load_run_id)
VALUES (%(program_id)s, %(chunk_index)s, %(text)s, %(start)s, %(end)s, %(sha)s,
        %(vec)s::vector, %(model)s, %(source_id)s, %(load_run_id)s)
ON CONFLICT (program_id, chunk_index, embedding_model_id) DO UPDATE
   SET chunk_text = EXCLUDED.chunk_text, char_start = EXCLUDED.char_start,
       char_end = EXCLUDED.char_end, content_sha256 = EXCLUDED.content_sha256,
       embedding = EXCLUDED.embedding, embedded_at = now()
"""


def main() -> None:
    """Read programs locally, chunk, embed (cached per text), upsert remotely."""
    if not config.EMBED_BASE:
        raise SystemExit("set EMBED_BASE (and EMBED_MODEL) to the embedding server first")
    started = time.perf_counter()
    with psycopg.connect(config.require("DATABASE_URL")) as local:
        programs = local.execute(SQL_PROGRAMS).fetchall()
    cache: dict[str, str] = {}
    written = 0
    with vector_store() as store:
        ensure_store(store)
        for program_id, source_id, load_run_id, description in programs:
            for chunk in chunk_description(description):
                vec = cache.get(chunk.content_sha256)
                if vec is None:
                    vec = vector_literal(embed(chunk.text))
                    cache[chunk.content_sha256] = vec
                store.execute(
                    SQL_UPSERT,
                    {
                        "program_id": program_id,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "start": chunk.char_start,
                        "end": chunk.char_end,
                        "sha": chunk.content_sha256,
                        "vec": vec,
                        "model": config.EMBED_MODEL_ID,
                        "source_id": source_id,
                        "load_run_id": load_run_id,
                    },
                )
                written += 1
            store.commit()
    print(
        f"{len(programs)} programs, {written} chunks upserted, {len(cache)} embeddings "
        f"computed, {time.perf_counter() - started:.0f} s, model {config.EMBED_MODEL}"
    )


if __name__ == "__main__":
    main()
