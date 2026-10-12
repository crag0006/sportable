"""The retrieval index over program descriptions (data/sql/013 and 014).

Dense candidates by cosine (pgvector, HNSW) and lexical candidates by BM25
over the three derived tables, fused by reciprocal rank. The acceptance rule
(floors, margins) is a service decision and lives in
``app.services.assistant.retrieval``; this module only ranks.
"""

import re
from typing import Any

from app.core.db import connection
from app.repositories.protocols import ChunkRow

K1 = 1.2
B = 0.75

SQL_HYBRID = """
WITH dense AS (
    SELECT chunk_id, 1 - (embedding <=> %(q)s::vector) AS similarity,
           row_number() OVER (ORDER BY embedding <=> %(q)s::vector) AS rnk
      FROM program_description_chunk
     WHERE embedding_model_id = %(model)s
     ORDER BY embedding <=> %(q)s::vector
     LIMIT %(cand)s
),
q AS (
    SELECT DISTINCT t.lexeme FROM unnest(to_tsvector('english', %(text)s)) AS t
),
corpus AS (
    SELECT count(*)::float AS n, avg(len) AS avglen FROM chunk_stats
),
lexical AS (
    SELECT ct.chunk_id,
           sum( ln((corpus.n - df.df + 0.5) / (df.df + 0.5) + 1)
                * ct.tf * (%(k1)s + 1)
                / (ct.tf + %(k1)s * (1 - %(b)s + %(b)s * cs.len / corpus.avglen)) ) AS bm25
      FROM q
      JOIN chunk_term  ct ON ct.lexeme = q.lexeme
      JOIN term_df     df ON df.lexeme = q.lexeme
      JOIN chunk_stats cs ON cs.chunk_id = ct.chunk_id
     CROSS JOIN corpus
     GROUP BY ct.chunk_id
     ORDER BY bm25 DESC
     LIMIT %(cand)s
),
ranked AS (
    SELECT chunk_id, bm25, row_number() OVER (ORDER BY bm25 DESC) AS rnk,
           (SELECT sum(ln((corpus.n - df.df + 0.5) / (df.df + 0.5) + 1) * (%(k1)s + 1))
              FROM q JOIN term_df df ON df.lexeme = q.lexeme CROSS JOIN corpus) AS max_bm25
      FROM lexical
)
SELECT c.program_id, c.chunk_index, c.chunk_text, c.source_id,
       coalesce(d.similarity, 1 - (c.embedding <=> %(q)s::vector)) AS similarity,
       r.chunk_id IS NOT NULL AS lexical_hit,
       CASE WHEN r.max_bm25 > 0 THEN r.bm25 / r.max_bm25 ELSE 0 END AS ratio,
       coalesce(1.0 / (60 + d.rnk), 0) + coalesce(1.0 / (60 + r.rnk), 0) AS fused
  FROM program_description_chunk c
  LEFT JOIN dense  d ON d.chunk_id = c.chunk_id
  LEFT JOIN ranked r ON r.chunk_id = c.chunk_id
 WHERE d.chunk_id IS NOT NULL OR r.chunk_id IS NOT NULL
 ORDER BY fused DESC
 LIMIT %(cand)s
"""

# Dense only, for a database without the BM25 tables (migration 014 pending).
SQL_DENSE = """
SELECT c.program_id, c.chunk_index, c.chunk_text, c.source_id,
       1 - (c.embedding <=> %(q)s::vector) AS similarity,
       false AS lexical_hit, 0.0 AS ratio
  FROM program_description_chunk c
 WHERE c.embedding_model_id = %(model)s
 ORDER BY c.embedding <=> %(q)s::vector
 LIMIT %(cand)s
"""

SQL_HAS_BM25 = "SELECT to_regclass('public.chunk_term') IS NOT NULL AS present"
SQL_TITLES = "SELECT program_id, name, source_url FROM program WHERE program_id = ANY(%(ids)s)"


def vector_literal(vector: list[float]) -> str:
    """A pgvector input literal."""
    return "[" + ",".join(f"{x:.8g}" for x in vector) + "]"


def _row(r: dict[str, Any]) -> ChunkRow:
    """One result row as a ``ChunkRow``; the BM25 ratio rides along for the acceptance rule."""
    return ChunkRow(
        program_id=r["program_id"],
        chunk_index=int(r["chunk_index"]),
        text=r["chunk_text"],
        source_id=r["source_id"],
        similarity=float(r["similarity"]),
        lexical_hit=bool(r["lexical_hit"]),
    )


class PostgresChunkRepository:
    """``ChunkRepository`` over pgvector and the BM25 tables."""

    def __init__(self) -> None:
        """The BM25 tables are looked for once per process."""
        self._has_bm25: bool | None = None
        self.last_ratios: dict[tuple[str, int], float] = {}

    def _bm25_available(self, conn: Any) -> bool:
        """Whether migration 014 has been applied here."""
        if self._has_bm25 is None:
            self._has_bm25 = bool(conn.execute(SQL_HAS_BM25).fetchone()["present"])
        return self._has_bm25

    def search(
        self, embedding: list[float], question: str, model_id: str, limit: int
    ) -> list[ChunkRow]:
        """Fused candidates, best first; ``last_ratios`` keeps each row's BM25 share."""
        text = " ".join(re.findall(r"[A-Za-z0-9']+", question))[:500]
        params = {
            "q": vector_literal(embedding),
            "model": model_id,
            "cand": limit,
            "text": text,
            "k1": K1,
            "b": B,
        }
        with connection() as conn:
            sql = SQL_HYBRID if self._bm25_available(conn) else SQL_DENSE
            rows = conn.execute(sql, params).fetchall()
        self.last_ratios = {
            (r["program_id"], int(r["chunk_index"])): float(r["ratio"]) for r in rows
        }
        return [_row(r) for r in rows]

    def titles(self, program_ids: list[str]) -> dict[str, tuple[str, str | None]]:
        """Program name and publisher page by id."""
        if not program_ids:
            return {}
        with connection() as conn:
            rows = conn.execute(SQL_TITLES, {"ids": program_ids}).fetchall()
        return {r["program_id"]: (r["name"], r["source_url"]) for r in rows}
