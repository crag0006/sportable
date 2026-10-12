"""Question -> embedding (embedding server) -> pgvector cosine search (vector store).

The lab splits what production keeps in one RDS database: the vector store is
the pgvector database on the lab server, the program rows stay in the local
PostGIS database. Retrieval therefore returns program ids from the vector store
and fetches titles and publisher pages from the local database afterwards.
"""

import re

import httpx
import psycopg

from lab import config

# No foreign keys: the program, source and load_run tables live in the other
# database. Same columns as migration 010 otherwise, so the SQL carries over.
SQL_CREATE = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS program_chunk (
    chunk_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    program_id         text NOT NULL,
    chunk_index        integer NOT NULL,
    chunk_text         text NOT NULL,
    char_start         integer NOT NULL,
    char_end           integer NOT NULL,
    content_sha256     char(64) NOT NULL,
    embedding          vector(%(dims)s) NOT NULL,
    embedding_model_id text NOT NULL,
    source_id          text NOT NULL,
    load_run_id        bigint,
    embedded_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT program_chunk_unique UNIQUE (program_id, chunk_index, embedding_model_id)
);
CREATE INDEX IF NOT EXISTS program_chunk_embedding_hnsw
    ON program_chunk USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
"""

SQL_SEARCH = """
SELECT program_id, chunk_index, chunk_text, source_id,
       1 - (embedding <=> %(q)s::vector) AS similarity
  FROM program_chunk
 WHERE embedding_model_id = %(model)s
 ORDER BY embedding <=> %(q)s::vector
 LIMIT %(k)s
"""

# Hybrid: dense cosine candidates and lexical (Postgres full-text) candidates,
# fused by reciprocal rank. A specific phrase ("audible tennis balls") is a
# small part of a 400-char chunk and scores poorly on dense similarity alone;
# the lexical leg catches it. The dense floor applies only to dense-only hits.
SQL_HYBRID = """
WITH dense AS (
    SELECT chunk_id, 1 - (embedding <=> %(q)s::vector) AS similarity,
           row_number() OVER (ORDER BY embedding <=> %(q)s::vector) AS rnk
      FROM program_chunk
     WHERE embedding_model_id = %(model)s
     ORDER BY embedding <=> %(q)s::vector
     LIMIT %(cand)s
),
lexical AS (
    SELECT chunk_id,
           ts_rank_cd(to_tsvector('english', chunk_text), to_tsquery('english', %(tsq)s)) AS lex,
           row_number() OVER (ORDER BY ts_rank_cd(to_tsvector('english', chunk_text),
                                                  to_tsquery('english', %(tsq)s)) DESC) AS rnk
      FROM program_chunk
     WHERE embedding_model_id = %(model)s
       AND to_tsvector('english', chunk_text) @@ to_tsquery('english', %(tsq)s)
     LIMIT %(cand)s
)
SELECT c.program_id, c.chunk_index, c.chunk_text, c.source_id,
       coalesce(d.similarity, 1 - (c.embedding <=> %(q)s::vector)) AS similarity,
       l.lex IS NOT NULL AS lexical_hit,
       coalesce(1.0 / (60 + d.rnk), 0) + coalesce(1.0 / (60 + l.rnk), 0) AS fused
  FROM program_chunk c
  LEFT JOIN dense d ON d.chunk_id = c.chunk_id
  LEFT JOIN lexical l ON l.chunk_id = c.chunk_id
 WHERE d.chunk_id IS NOT NULL OR l.chunk_id IS NOT NULL
 ORDER BY fused DESC
 LIMIT %(k)s
"""

SQL_TITLES = """
SELECT program_id, name, source_url FROM program WHERE program_id = ANY(%(ids)s)
"""


# Words that carry no content in a question about programs. The lexical leg
# ORs the remaining words, so "Which programs mention audible tennis balls?"
# becomes 'audible | tennis | balls' and ts_rank_cd rewards chunks matching most.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "any",
        "are",
        "can",
        "could",
        "do",
        "does",
        "did",
        "for",
        "from",
        "have",
        "has",
        "how",
        "i",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "their",
        "there",
        "these",
        "this",
        "those",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "program",
        "programs",
        "mention",
        "mentions",
        "say",
        "says",
        "said",
        "describe",
        "about",
        "near",
        "around",
        "please",
        "tell",
        "find",
        "list",
        "give",
        "show",
        "know",
        "want",
        "like",
    ]
)


def lexical_query(question: str) -> str:
    """The OR'd content words of a question as a ``to_tsquery`` string; empty when none."""
    words = [w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) > 2 and w not in STOPWORDS]
    return " | ".join(dict.fromkeys(words))


def _matched(terms: list[str], text: str) -> int:
    """How many distinct query terms occur in the chunk (crude stem: drop the last two letters)."""
    low = text.lower()
    return sum(1 for t in terms if re.search(r"\b" + re.escape(t[: max(4, len(t) - 2)]), low))


def _keep(similarity: float, lexical: bool, matched: int) -> bool:
    """The hybrid acceptance rule.

    Dense alone must clear the floor. A lexical hit may sit below it only when
    the chunk carries at least two of the question's content words and is not
    far below (LEXICAL_MARGIN), or carries three or more words whatever the
    score: "audible tennis balls" is a phrase, "accessible parking" is not.
    """
    if similarity >= config.RELEVANCE_FLOOR:
        return True
    if not lexical:
        return False
    if matched >= 3:
        return True
    return matched >= 2 and similarity >= config.RELEVANCE_FLOOR - config.LEXICAL_MARGIN


def vector_store() -> psycopg.Connection:
    """A connection to the pgvector database."""
    return psycopg.connect(config.require("VECTOR_DATABASE_URL"), connect_timeout=10)


def ensure_store(conn: psycopg.Connection) -> None:
    """Create the chunk table and HNSW index when absent."""
    conn.execute(SQL_CREATE.replace("%(dims)s", str(config.EMBED_DIMENSIONS)))
    conn.commit()


def embed(text: str) -> list[float]:
    """One embedding from the OpenAI-compatible /v1/embeddings endpoint."""
    r = httpx.post(
        f"{config.require('EMBED_BASE').rstrip('/')}/embeddings",
        json={"model": config.EMBED_MODEL, "input": text},
        timeout=60,
    )
    r.raise_for_status()
    vec = r.json()["data"][0]["embedding"]
    if len(vec) != config.EMBED_DIMENSIONS:
        raise RuntimeError(f"embedding has {len(vec)} dimensions, table wants {config.EMBED_DIMENSIONS}")
    return vec


def vector_literal(vec: list[float]) -> str:
    """A pgvector input literal."""
    return "[" + ",".join(f"{x:.8g}" for x in vec) + "]"


def _titles(ids: list[str]) -> dict[str, tuple[str, str | None]]:
    """Program names and publisher pages from the local database."""
    if not ids:
        return {}
    with psycopg.connect(config.require("DATABASE_URL")) as conn:
        rows = conn.execute(SQL_TITLES, {"ids": ids}).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


SQL_DENSE_CANDIDATES = """
SELECT chunk_id, program_id, chunk_index, chunk_text, source_id,
       1 - (embedding <=> %(q)s::vector) AS similarity,
       row_number() OVER (ORDER BY embedding <=> %(q)s::vector) AS rnk
  FROM program_chunk
 WHERE embedding_model_id = %(model)s
 ORDER BY embedding <=> %(q)s::vector
 LIMIT %(cand)s
"""
SQL_CHUNKS_BY_ID = """
SELECT chunk_id, program_id, chunk_index, chunk_text, source_id,
       1 - (embedding <=> %(q)s::vector) AS similarity
  FROM program_chunk WHERE chunk_id = ANY(%(ids)s)
"""


def _keep_bm25(similarity: float, ratio: float | None) -> bool:
    """Acceptance for the BM25 leg: dense floor, or enough of the query's IDF mass."""
    if similarity >= config.RELEVANCE_FLOOR:
        return True
    if ratio is None:
        return False
    if ratio >= config.BM25_RATIO_FLOOR:
        return True
    return ratio >= config.BM25_RATIO_SOFT and similarity >= config.RELEVANCE_FLOOR - config.LEXICAL_MARGIN


def _bm25_hybrid(conn: psycopg.Connection, q: str, question: str) -> list[tuple]:
    """Dense top candidates and BM25 top candidates, reciprocal-rank fused, then accepted.

    Returns rows shaped like SQL_SEARCH plus a lexical flag, best first.
    """
    from lab.bm25 import bm25_candidates

    cand = config.RETRIEVAL_TOP_K * 3
    params = {"q": q, "model": config.EMBED_MODEL_ID, "cand": cand}
    dense = {r[0]: r for r in conn.execute(SQL_DENSE_CANDIDATES, params).fetchall()}
    lexical = {c: (rnk, ratio) for c, _s, _m, rnk, ratio in bm25_candidates(conn, question, cand)}
    fused = {
        cid: (1 / (60 + dense[cid][6]) if cid in dense else 0) + (1 / (60 + lexical[cid][0]) if cid in lexical else 0)
        for cid in set(dense) | set(lexical)
    }
    missing = [cid for cid in lexical if cid not in dense]
    rows = {cid: r[:6] for cid, r in dense.items()}
    if missing:
        for r in conn.execute(SQL_CHUNKS_BY_ID, {"q": q, "ids": missing}).fetchall():
            rows[r[0]] = r
    out = []
    for cid in sorted(fused, key=lambda c: -fused[c]):
        r = rows[cid]
        ratio = lexical[cid][1] if cid in lexical else None
        if _keep_bm25(float(r[5]), ratio):
            out.append((r[1], r[2], r[3], r[4], r[5], cid in lexical))
    return out


def search_chunks(question: str) -> dict:
    """Top-k passages, hybrid or dense per RETRIEVAL_HYBRID, with program id, title and source.

    Hybrid is dense cosine plus a lexical leg (BM25 by default, ts_rank as the
    fallback), fused by reciprocal rank. A dense-only candidate must clear the
    floor; a lexical hit may sit below it under the leg's own rule.
    """
    q = vector_literal(embed(question))
    params = {"q": q, "model": config.EMBED_MODEL_ID, "k": config.RETRIEVAL_TOP_K}
    with vector_store() as conn:
        tsq = lexical_query(question)
        if config.RETRIEVAL_HYBRID and config.RETRIEVAL_LEXICAL == "bm25":
            rows = _bm25_hybrid(conn, q, question)
        elif config.RETRIEVAL_HYBRID and tsq:
            params.update({"tsq": tsq, "cand": config.RETRIEVAL_TOP_K * 3})
            terms = tsq.split(" | ")
            rows = [
                r
                for r in conn.execute(SQL_HYBRID, params).fetchall()
                if _keep(float(r[4]), bool(r[5]), _matched(terms, r[2]))
            ]
        else:
            rows = [
                (*r, False)
                for r in conn.execute(SQL_SEARCH, params).fetchall()
                if float(r[4]) >= config.RELEVANCE_FLOOR
            ]
    kept = rows[: config.RETRIEVAL_TOP_K]
    titles = _titles(sorted({r[0] for r in kept}))
    passages = [
        {
            "program_id": r[0],
            "title": titles.get(r[0], (None, None))[0],
            "text": r[2],
            "source_id": r[3],
            "publisher_page": titles.get(r[0], (None, None))[1],
            "similarity": round(float(r[4]), 3),
            "lexical_hit": bool(r[5]),
            "href": f"/events/{r[0]}",
        }
        for r in kept
    ]
    return {
        "available": True,
        "passages": passages,
        "floor": config.RELEVANCE_FLOOR,
        "note": "Passages are the publisher's own words about a program; quote them as such.",
    }
