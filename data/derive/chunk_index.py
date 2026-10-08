"""Build and maintain program_description_chunk from program.description.

Idempotent. A chunk is identified by (program_id, chunk_index, model). Per run:

    unchanged   same text, offsets and run      -> untouched
    relocated   same text, offsets/run differ   -> cheap UPDATE, no embedding
    written     new or changed text             -> vector from the SHA-256 cache
                                                   or from Bedrock, then upserted
    stale       no longer wanted                -> deleted

All Bedrock calls happen BEFORE any write, so a failed call leaves the previous
index intact. The caller owns the transaction (commit on clean exit).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from derive.chunker import Chunk, chunk_description

LOG = logging.getLogger("sportable.derive.chunk_index")

# A run that would delete more than this share of the index is almost certainly
# a broken load, not a publisher clearing out half its programmes.
MIN_ROWS_FOR_GUARD = 50
MAX_STALE_FRACTION = 0.5


class IndexAbortedError(RuntimeError):
    pass


class Embedder(Protocol):
    model_id: str

    def embed(self, text: str) -> list[float]: ...


@dataclass
class IndexOutcome:
    programmes: int
    programmes_without_text: int
    chunks_wanted: int
    unchanged: int
    relocated: int
    written: int
    embedded_new: int
    reused_vectors: int
    deleted: int


@dataclass
class _Wanted:
    chunk: Chunk
    source_id: str
    load_run_id: int


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.8g}" for x in vector) + "]"


def _cached_vectors(conn: Any, model_id: str, shas: set[str]) -> dict[str, str]:
    """Vectors already stored for these chunk texts, as pgvector literals."""
    if not shas:
        return {}

    rows = conn.execute(
        """
        SELECT DISTINCT ON (content_sha256)
               content_sha256::text AS sha, embedding::text AS vec
          FROM public.program_description_chunk
         WHERE embedding_model_id = %s
           AND content_sha256 = ANY(%s::text[])
         ORDER BY content_sha256
        """,
        (model_id, sorted(shas)),
    ).fetchall()

    return {row["sha"]: row["vec"] for row in rows}


def build_index(conn: Any, embedder: Embedder, *, allow_large_delete: bool = False) -> IndexOutcome:
    model_id = embedder.model_id

    programs = conn.execute(
        "SELECT program_id, description, source_id, load_run_id FROM public.program "
        "ORDER BY program_id"
    ).fetchall()

    wanted: dict[tuple[str, int], _Wanted] = {}
    without_text = 0

    for row in programs:
        chunks = chunk_description(row["description"])

        if not chunks:
            without_text += 1
            continue

        for chunk in chunks:
            wanted[(row["program_id"], chunk.chunk_index)] = _Wanted(
                chunk, row["source_id"], row["load_run_id"]
            )

    existing = {
        (row["program_id"], row["chunk_index"]): row
        for row in conn.execute(
            """
            SELECT program_id, chunk_index, content_sha256::text AS sha,
                   char_start, char_end, source_id, load_run_id
              FROM public.program_description_chunk
             WHERE embedding_model_id = %s
            """,
            (model_id,),
        ).fetchall()
    }

    stale = [key for key in existing if key not in wanted]

    if (
        not allow_large_delete
        and len(existing) >= MIN_ROWS_FOR_GUARD
        and len(stale) > len(existing) * MAX_STALE_FRACTION
    ):
        raise IndexAbortedError(
            f"Run would delete {len(stale)} of {len(existing)} chunks. Inspect program "
            "before rerunning with allow_large_delete."
        )

    unchanged = 0
    relocated: list[tuple[Any, ...]] = []
    to_write: list[tuple[tuple[str, int], _Wanted]] = []

    for key, want in wanted.items():
        current = existing.get(key)
        chunk = want.chunk

        if current is not None and current["sha"] == chunk.content_sha256:
            same_place = (
                current["char_start"] == chunk.char_start
                and current["char_end"] == chunk.char_end
                and current["source_id"] == want.source_id
                and current["load_run_id"] == want.load_run_id
            )

            if same_place:
                unchanged += 1
            else:
                relocated.append(
                    (
                        chunk.char_start,
                        chunk.char_end,
                        want.source_id,
                        want.load_run_id,
                        key[0],
                        key[1],
                        model_id,
                    )
                )
            continue

        to_write.append((key, want))

    # ---- every Bedrock call happens here, before any write -------------------
    cache = _cached_vectors(conn, model_id, {w.chunk.content_sha256 for _, w in to_write})
    fresh: dict[str, str] = {}
    embedded_new = 0
    reused = 0
    upserts: list[tuple[Any, ...]] = []

    for (program_id, chunk_index), want in to_write:
        sha = want.chunk.content_sha256
        literal = cache.get(sha) or fresh.get(sha)

        if literal is None:
            literal = _vector_literal(embedder.embed(want.chunk.text))
            fresh[sha] = literal
            embedded_new += 1
        else:
            reused += 1

        upserts.append(
            (
                program_id,
                chunk_index,
                want.chunk.text,
                want.chunk.char_start,
                want.chunk.char_end,
                sha,
                literal,
                model_id,
                want.source_id,
                want.load_run_id,
            )
        )

    # ---- writes ---------------------------------------------------------------
    with conn.cursor() as cur:
        if stale:
            cur.executemany(
                "DELETE FROM public.program_description_chunk "
                "WHERE program_id = %s AND chunk_index = %s AND embedding_model_id = %s",
                [(program_id, index, model_id) for program_id, index in stale],
            )

        if relocated:
            cur.executemany(
                "UPDATE public.program_description_chunk "
                "SET char_start = %s, char_end = %s, source_id = %s, load_run_id = %s "
                "WHERE program_id = %s AND chunk_index = %s AND embedding_model_id = %s",
                relocated,
            )

        if upserts:
            cur.executemany(
                """
                INSERT INTO public.program_description_chunk
                    (program_id, chunk_index, chunk_text, char_start, char_end,
                     content_sha256, embedding, embedding_model_id, source_id, load_run_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
                ON CONFLICT (program_id, chunk_index, embedding_model_id) DO UPDATE SET
                    chunk_text     = EXCLUDED.chunk_text,
                    char_start     = EXCLUDED.char_start,
                    char_end       = EXCLUDED.char_end,
                    content_sha256 = EXCLUDED.content_sha256,
                    embedding      = EXCLUDED.embedding,
                    source_id      = EXCLUDED.source_id,
                    load_run_id    = EXCLUDED.load_run_id,
                    embedded_at    = now()
                """,
                upserts,
            )

    conn.execute("ANALYZE public.program_description_chunk")

    return IndexOutcome(
        programmes=len(programs),
        programmes_without_text=without_text,
        chunks_wanted=len(wanted),
        unchanged=unchanged,
        relocated=len(relocated),
        written=len(upserts),
        embedded_new=embedded_new,
        reused_vectors=reused,
        deleted=len(stale),
    )
