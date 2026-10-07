from itertools import pairwise

import pytest
from derive.chunker import MAX_CHUNK_CHARS, chunk_description


def test_none_and_blank_give_no_chunks():
    assert chunk_description(None) == []
    assert chunk_description("") == []
    assert chunk_description("   ") == []


def test_short_text_is_one_chunk_with_exact_offsets():
    text = "Bring a water bottle and wear sports shoes."
    chunks = chunk_description(text)
    assert len(chunks) == 1
    assert (chunks[0].char_start, chunks[0].char_end) == (0, len(text))
    assert chunks[0].text == text


def _long_text() -> str:
    return " ".join(
        f"Sentence number {i} says to bring water and a towel to the session." for i in range(40)
    )


def test_long_text_chunks_are_bounded_contiguous_and_faithful():
    text = _long_text()
    chunks = chunk_description(text)

    assert len(chunks) > 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)

    for previous, current in pairwise(chunks):
        assert current.char_start < previous.char_end  # they overlap
        assert current.char_start > previous.char_start  # and make progress

    for chunk in chunks:
        assert len(chunk.text) <= MAX_CHUNK_CHARS
        assert chunk.text == text[chunk.char_start : chunk.char_end]
        assert len(chunk.content_sha256) == 64


def test_prefers_sentence_boundaries():
    chunks = chunk_description(_long_text())
    assert all(c.text.endswith(".") for c in chunks)


def test_deterministic():
    assert chunk_description(_long_text()) == chunk_description(_long_text())


def test_text_without_punctuation_splits_on_spaces():
    text = " ".join(["word"] * 400)
    chunks = chunk_description(text)
    assert len(chunks) > 1
    assert all(not c.text.startswith(" ") and not c.text.endswith(" ") for c in chunks)
    assert chunks[-1].char_end == len(text)


def test_one_giant_token_still_terminates_and_covers():
    text = "x" * 1500
    chunks = chunk_description(text)
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == 1500
    assert all(len(c.text) <= MAX_CHUNK_CHARS for c in chunks)


def test_leading_and_trailing_whitespace_not_in_chunks():
    chunks = chunk_description("  hello world.  ")
    assert chunks[0].text == "hello world."


@pytest.mark.parametrize("n", [500, 560, 561, 1000])
def test_boundary_lengths_cover_everything(n):
    text = ("ab " * n)[:n].strip()
    chunks = chunk_description(text)
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)