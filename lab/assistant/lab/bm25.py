"""BM25 over the chunk store, in plain SQL, so it runs on RDS where no BM25 extension can be installed.

Index: three small tables derived from ``to_tsvector('english', chunk_text)``
  chunk_term  (chunk_id, lexeme, tf)      term frequency per chunk
  chunk_stats (chunk_id, len)             chunk length in lexemes
  term_df     (lexeme, df)                document frequency per lexeme
Rebuilt whole by ``build_index`` after every chunk load (seconds at this size).

Query: the question's lexemes through the same dictionary, then the textbook
formula with k1 = 1.2, b = 0.75.
"""

import psycopg

from lab import config

SQL_BUILD = """
DROP TABLE IF EXISTS chunk_term; DROP TABLE IF EXISTS chunk_stats; DROP TABLE IF EXISTS term_df;
CREATE TABLE chunk_term AS
    SELECT c.chunk_id, t.lexeme, array_length(t.positions, 1) AS tf
      FROM program_chunk c, unnest(to_tsvector('english', c.chunk_text)) AS t
     WHERE c.embedding_model_id = %(model)s;
CREATE INDEX chunk_term_lexeme ON chunk_term (lexeme);
CREATE TABLE chunk_stats AS
    SELECT chunk_id, sum(tf)::float AS len FROM chunk_term GROUP BY chunk_id;
CREATE TABLE term_df AS
    SELECT lexeme, count(DISTINCT chunk_id) AS df FROM chunk_term GROUP BY lexeme;
CREATE INDEX term_df_lexeme ON term_df (lexeme);
"""

SQL_BM25 = """
WITH q AS (
    SELECT DISTINCT t.lexeme FROM unnest(to_tsvector('english', %(text)s)) AS t
),
corpus AS (
    SELECT count(*)::float AS n, avg(len) AS avglen FROM chunk_stats
),
scored AS (
    SELECT ct.chunk_id,
           sum( ln((corpus.n - df.df + 0.5) / (df.df + 0.5) + 1)
                * ct.tf * (%(k1)s + 1)
                / (ct.tf + %(k1)s * (1 - %(b)s + %(b)s * cs.len / corpus.avglen)) ) AS bm25,
           count(*) AS matched_terms
      FROM q
      JOIN chunk_term  ct ON ct.lexeme = q.lexeme
      JOIN term_df     df ON df.lexeme = q.lexeme
      JOIN chunk_stats cs ON cs.chunk_id = ct.chunk_id
     CROSS JOIN corpus
     GROUP BY ct.chunk_id
)
SELECT chunk_id, bm25, matched_terms,
       row_number() OVER (ORDER BY bm25 DESC) AS rnk,
       -- the score a chunk would get if it matched every query term at saturation
       (SELECT sum(ln((corpus.n - df.df + 0.5) / (df.df + 0.5) + 1) * (%(k1)s + 1))
          FROM q JOIN term_df df ON df.lexeme = q.lexeme CROSS JOIN corpus) AS max_bm25
  FROM scored
 ORDER BY bm25 DESC
 LIMIT %(cand)s
"""

K1 = 1.2
B = 0.75


def build_index(conn: psycopg.Connection) -> dict[str, int]:
    """Rebuild the three BM25 tables for the current model's chunks; returns row counts."""
    for statement in SQL_BUILD.split(";"):
        if statement.strip():
            conn.execute(statement, {"model": config.EMBED_MODEL_ID})
    conn.commit()
    return {
        t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in ("chunk_term", "chunk_stats", "term_df")
    }


def bm25_candidates(conn: psycopg.Connection, question: str, cand: int) -> list[tuple[int, float, int, int, float]]:
    """``(chunk_id, bm25, matched_terms, rank, ratio)`` for the top candidates.

    ``ratio`` is bm25 divided by the query's maximum attainable score, so it is
    comparable across queries: 1.0 means every query term matched at saturation.
    """
    rows = conn.execute(SQL_BM25, {"text": question, "k1": K1, "b": B, "cand": cand}).fetchall()
    return [(r[0], float(r[1]), int(r[2]), int(r[3]), float(r[1]) / float(r[4]) if r[4] else 0.0) for r in rows]
