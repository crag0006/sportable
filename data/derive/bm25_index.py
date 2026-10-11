"""BM25 index over program_description_chunk, in plain SQL.

Three small tables derived from to_tsvector('english', chunk_text), exactly the
shapes lab/assistant/lab/bm25.py builds and queries (k1 = 1.2, b = 0.75):

    chunk_term  (chunk_id, lexeme, tf)   term frequency per chunk
    chunk_stats (chunk_id, len)          chunk length in lexemes
    term_df     (lexeme, df)             document frequency per lexeme

Rebuilt whole after every chunk run: a few thousand rows, well under a second.
The tables are created by migration 014. The only difference from the lab
version is the source table: the lab calls it program_chunk, this is
program_description_chunk.

TRUNCATE is transactional, so a reader sees the old tables until the caller
commits. It takes an exclusive lock, so a reader arriving mid-rebuild waits for
that commit rather than seeing a half-built index.

The caller owns the transaction.
"""

from __future__ import annotations

from typing import Any

SQL_TRUNCATE = "TRUNCATE public.chunk_term, public.chunk_stats, public.term_df"

SQL_TERMS = """
INSERT INTO public.chunk_term (chunk_id, lexeme, tf)
SELECT c.chunk_id, t.lexeme, array_length(t.positions, 1)
  FROM public.program_description_chunk c,
       unnest(to_tsvector('english', c.chunk_text)) AS t
 WHERE c.embedding_model_id = %s
"""

SQL_STATS = """
INSERT INTO public.chunk_stats (chunk_id, len)
SELECT chunk_id, sum(tf)::float
  FROM public.chunk_term
 GROUP BY chunk_id
"""

SQL_DF = """
INSERT INTO public.term_df (lexeme, df)
SELECT lexeme, count(DISTINCT chunk_id)
  FROM public.chunk_term
 GROUP BY lexeme
"""

SQL_COUNTS = {
    "chunk_term": "SELECT count(*) AS n FROM public.chunk_term",
    "chunk_stats": "SELECT count(*) AS n FROM public.chunk_stats",
    "term_df": "SELECT count(*) AS n FROM public.term_df",
}


def rebuild(conn: Any, model_id: str) -> dict[str, int]:
    """Rebuild the three tables for this model's chunks. Returns row counts."""
    conn.execute(SQL_TRUNCATE)
    conn.execute(SQL_TERMS, (model_id,))
    conn.execute(SQL_STATS)
    conn.execute(SQL_DF)
    conn.execute("ANALYZE public.chunk_term, public.chunk_stats, public.term_df")

    return {name: int(conn.execute(sql).fetchone()["n"]) for name, sql in SQL_COUNTS.items()}
