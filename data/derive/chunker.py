"""Split programme descriptions into overlapping chunks for retrieval.

Pure functions: no database, no AWS. ds09_aaaplay already strips HTML and
collapses whitespace before program.description is stored, so this works on the
stored text as-is and char_start/char_end index straight into it. Do NOT
normalise the text here, or the offsets stop meaning anything.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

TARGET_CHARS = 500
OVERLAP_CHARS = 80
# A remainder this close to the target stays in the final chunk rather than
# becoming a tiny, mostly-overlap chunk of its own.
TAIL_SLACK_CHARS = 60
MIN_FILL_CHARS = TARGET_CHARS // 2

MAX_CHUNK_CHARS = TARGET_CHARS + TAIL_SLACK_CHARS

_SENTENCE_END = re.compile(r"[.!?][\"')\]]*(?=\s)")


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    content_sha256: str


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _break_point(text: str, start: int, limit: int) -> int:
    """End (exclusive) for a chunk starting at `start` that may not pass `limit`.

    Prefers the last sentence end in the back half of the window, then the last
    space, then a hard cut.
    """
    floor = start + MIN_FILL_CHARS
    best: int | None = None

    # limit + 1 so a sentence ending exactly at the limit can see its trailing space.
    for match in _SENTENCE_END.finditer(text, start, min(limit + 1, len(text))):
        position = match.end()
        if floor <= position <= limit:
            best = position

    if best is not None:
        return best

    space = text.rfind(" ", floor, limit)
    return space if space != -1 else limit


def _next_start(text: str, start: int, end: int) -> int:
    """Start of the following chunk: about OVERLAP_CHARS back, on a word boundary."""
    candidate = max(end - OVERLAP_CHARS, start + 1)
    space = text.find(" ", candidate, end)
    position = space + 1 if space != -1 else candidate

    while position < len(text) and text[position].isspace():
        position += 1

    return position


def chunk_description(description: str | None) -> list[Chunk]:
    """Chunks for one description. None, empty or blank gives no chunks."""
    if description is None or not description.strip():
        return []

    text = description
    begin = len(text) - len(text.lstrip())
    stop = len(text.rstrip())

    spans: list[tuple[int, int]] = []
    start = begin

    while True:
        if stop - start <= MAX_CHUNK_CHARS:
            end = stop
        else:
            end = _break_point(text, start, start + TARGET_CHARS)

        spans.append((start, end))

        if end >= stop:
            break

        start = _next_start(text, start, end)

    return [
        Chunk(
            chunk_index=index,
            text=text[s:e],
            char_start=s,
            char_end=e,
            content_sha256=_sha256(text[s:e]),
        )
        for index, (s, e) in enumerate(spans)
    ]
