"""Build and maintain program_description_chunk from program.description.

Idempotent and resumable. A chunk is identified by (program_id, chunk_index, model).
Per run:

    unchanged   same text, offsets and run      -> untouched
    relocated   same text, offsets/run differ   -> cheap UPDATE, no embedding
    written     new or changed text             -> vector from the SHA-256 cache
                                                   or from Bedrock, upserted in batches
    stale       no longer wanted                -> deleted, but only after every
                                                   batch has been written

Bedrock calls run in a small thread pool, one batch at a time. After each batch
the caller's checkpoint commits it, so a timeout or a failure later in the run
keeps the earlier batches, and the next run carries on from there: finished
chunks are found by their SHA-256 and cost nothing. Without the checkpoints a
first build that outlasts the Lambda would store nothing at all.

checkpoint is None in tests, which run in one transaction that is rolled back.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from derive.chunker import Chunk, chunk_description

LOG = logging.getLogger("sportable.derive.chunk_index")

# A run that would delete more than this share of the index is almost certainly
# a broken load, not a publisher clearing out half its programmes.
MIN_ROWS_FOR_GUARD = 50
MAX_STALE_FRACTION = 0.5

DEFAULT_BATCH_SIZE = 50
DEFAULT_WORKERS = 4
# Stop starting new batches when less than this is left, so the last commit and
# the BM25 rebuild that follows always have room.
DEFAULT_RESERVE_SECONDS = 60.0


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
    complete: bool = True
    pending: int = 0
    batches: int = 0


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


def _embed_texts(embedder: Embedder, texts: dict[str, str], workers: int) -> dict[str, str]:
    """Vector literal per SHA-256, embedding the texts in parallel.

    The first exception wins. Calls already in flight finish before it
    propagates, which is at most `workers` of them.
    """
    if workers <= 1 or len(texts) <= 1:
        return {sha: _vector_literal(embedder.embed(text)) for sha, text in texts.items()}

    with ThreadPoolExecutor(max_workers=min(workers, len(texts))) as pool:
        futures = {sha: pool.submit(embedder.embed, text) for sha, text in texts.items()}
        return {sha: _vector_literal(future.result()) for sha, future in futures.items()}


def build_index(
    conn: Any,
    embedder: Embedder,
    *,
    allow_large_delete: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    workers: int = DEFAULT_WORKERS,
    checkpoint: Callable[[], None] | None = None,
    time_left: Callable[[], float] | None = None,
    reserve_seconds: float = DEFAULT_RESERVE_SECONDS,
) -> IndexOutcome:
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

    # Raised before anything is written, so a refused run changes nothing.
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

    # ---- cheap in-place fixes first: no Bedrock, nothing to lose --------------
    if relocated:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE public.program_description_chunk "
                "SET char_start = %s, char_end = %s, source_id = %s, load_run_id = %s "
                "WHERE program_id = %s AND chunk_index = %s AND embedding_model_id = %s",
                relocated,
            )

        if checkpoint:
            checkpoint()

    # ---- embed and write, one committed batch at a time ----------------------
    vectors = _cached_vectors(conn, model_id, {w.chunk.content_sha256 for _, w in to_write})
    embedded_new = 0
    reused = 0
    written = 0
    batches = 0
    pending = len(to_write)

    for offset in range(0, len(to_write), max(batch_size, 1)):
        if time_left is not None and time_left() < reserve_seconds:
            break

        batch = to_write[offset : offset + max(batch_size, 1)]

        # Texts this batch still has to embed, one per distinct SHA-256.
        texts: dict[str, str] = {}
        for _, want in batch:
            sha = want.chunk.content_sha256
            if sha not in vectors and sha not in texts:
                texts[sha] = want.chunk.text

        vectors.update(_embed_texts(embedder, texts, workers))
        embedded_new += len(texts)
        reused += len(batch) - len(texts)

        rows = [
            (
                program_id,
                index,
                want.chunk.text,
                want.chunk.char_start,
                want.chunk.char_end,
                want.chunk.content_sha256,
                vectors[want.chunk.content_sha256],
                model_id,
                want.source_id,
                want.load_run_id,
            )
            for (program_id, index), want in batch
        ]

        with conn.cursor() as cur:
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
                rows,
            )

        if checkpoint:
            checkpoint()

        written += len(rows)
        pending -= len(rows)
        batches += 1

    # ---- stale chunks go only once everything wanted has been written --------
    complete = pending == 0

    if complete and stale:
        with conn.cursor() as cur:
            cur.executemany(
                "DELETE FROM public.program_description_chunk "
                "WHERE program_id = %s AND chunk_index = %s AND embedding_model_id = %s",
                [(program_id, index, model_id) for program_id, index in stale],
            )

        if checkpoint:
            checkpoint()

    if not complete:
        LOG.warning("index incomplete: %d chunks still to embed", pending)

    conn.execute("ANALYZE public.program_description_chunk")

    return IndexOutcome(
        programmes=len(programs),
        programmes_without_text=without_text,
        chunks_wanted=len(wanted),
        unchanged=unchanged,
        relocated=len(relocated),
        written=written,
        embedded_new=embedded_new,
        reused_vectors=reused,
        deleted=len(stale) if complete else 0,
        complete=complete,
        pending=pending,
        batches=batches,
    )
