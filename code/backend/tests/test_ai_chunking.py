"""Tests for splitting long documents."""

from app.ai.chunking import CHUNK_SIZE, MAX_CHUNKS, split_text


def _words_only(text):
    return "".join(text.split())


def test_a_document_that_fits_in_one_chunk_isnt_split():
    assert split_text("x" * CHUNK_SIZE) == []


def test_the_chunk_count_follows_the_length():
    assert len(split_text("word " * (CHUNK_SIZE // 5 + 1000))) == 2


def test_the_chunk_count_never_passes_the_maximum():
    assert len(split_text("word " * 100_000)) == MAX_CHUNKS


def test_no_content_is_lost():
    text = "\n\n".join(f"Paragraph {n} has some words in it." for n in range(3000))
    assert _words_only("".join(split_text(text))) == _words_only(text)


def test_a_paragraph_break_is_preferred():
    text = "a " * 11_000 + "\n\n" + "b " * 13_000
    first, second = split_text(text)
    assert "b" not in first
    assert "a" not in second


def test_text_without_whitespace_is_still_split():
    chunks = split_text("x" * (CHUNK_SIZE * 2))
    assert len(chunks) == 2
    assert sum(len(chunk) for chunk in chunks) == CHUNK_SIZE * 2
