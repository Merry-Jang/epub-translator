"""청크 분할 모듈 단위 테스트."""

import pytest

from src.epub_parser import Chapter, TextBlock
from src.chunker import chunk_chapter, Chunk


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def make_chapter(
    blocks_data: list[tuple[str, int]],
    chapter_id: str = "ch00",
) -> Chapter:
    """테스트용 Chapter 생성. blocks_data = [(text, word_count), ...]"""
    blocks = [
        TextBlock(index=i, text=text, tag="p", word_count=wc)
        for i, (text, wc) in enumerate(blocks_data)
    ]
    return Chapter(
        id=chapter_id,
        title="Test Chapter",
        href="chapter.xhtml",
        content="",
        text_blocks=blocks,
    )


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_short_text_single_chunk():
    """max_words 미만 텍스트 → 청크 1개."""
    chapter = make_chapter([
        ("This is a short paragraph.", 5),
        ("Another short paragraph.", 4),
    ])

    chunks = chunk_chapter(chapter, max_words=800)

    assert len(chunks) == 1
    assert chunks[0].chapter_id == "ch00"


def test_long_text_multiple_chunks():
    """max_words 초과 텍스트 → 여러 청크, 각 청크 word_count ≤ max_words."""
    # 500 × 2 = 1000 words, max=800 → 2 chunks
    chapter = make_chapter([
        ("word " * 499 + "end.", 500),
        ("word " * 499 + "end.", 500),
    ])

    chunks = chunk_chapter(chapter, max_words=800)

    assert len(chunks) == 2
    for chunk in chunks:
        total = sum(chapter.text_blocks[i].word_count for i in chunk.block_indices)
        # 단일 블록이 초과하는 경우는 허용 (규칙 3)
        assert total <= 800 or len(chunk.block_indices) == 1


def test_empty_blocks_returns_empty_list():
    """빈 블록 리스트 → 빈 청크 리스트."""
    chapter = Chapter(
        id="ch00",
        title="Empty",
        href="empty.xhtml",
        content="",
        text_blocks=[],
    )

    chunks = chunk_chapter(chapter, max_words=800)

    assert chunks == []


def test_block_indices_single_chunk():
    """단일 청크일 때 block_indices = [0, 1, 2, ...]."""
    chapter = make_chapter([
        ("Para 0.", 10),
        ("Para 1.", 10),
        ("Para 2.", 10),
    ])

    chunks = chunk_chapter(chapter, max_words=800)

    assert len(chunks) == 1
    assert chunks[0].block_indices == [0, 1, 2]


def test_block_indices_multiple_chunks():
    """여러 청크로 분할 시 block_indices 연속성 — 합치면 0..N-1."""
    chapter = make_chapter([
        ("A " * 499 + "end.", 500),
        ("B " * 499 + "end.", 500),
        ("C " * 499 + "end.", 500),
    ])

    chunks = chunk_chapter(chapter, max_words=800)

    all_indices = []
    for chunk in chunks:
        all_indices.extend(chunk.block_indices)

    assert sorted(all_indices) == list(range(3))


def test_chunk_text_joined_by_double_newline():
    """청크 텍스트 = 블록들을 \\n\\n으로 조인."""
    chapter = make_chapter([
        ("Para one.", 2),
        ("Para two.", 2),
    ])

    chunks = chunk_chapter(chapter, max_words=800)

    assert chunks[0].text == "Para one.\n\nPara two."


def test_chunk_id_format():
    """청크 ID = {chapter_id}_chunk{index:02d}."""
    chapter = make_chapter([("Hello.", 1)])

    chunks = chunk_chapter(chapter, max_words=800)

    assert chunks[0].id == "ch00_chunk00"


def test_chunk_id_increments():
    """청크 인덱스가 순서대로 증가."""
    chapter = make_chapter([
        ("A " * 499 + "end.", 500),
        ("B " * 499 + "end.", 500),
        ("C " * 499 + "end.", 500),
    ])

    chunks = chunk_chapter(chapter, max_words=800)

    assert chunks[0].id == "ch00_chunk00"
    assert chunks[1].id == "ch00_chunk01"


def test_single_block_exceeds_max_words_still_one_chunk():
    """단일 블록이 max_words 초과 시 → 그 블록만으로 1개 청크 (규칙 3)."""
    chapter = make_chapter([
        ("word " * 999 + "end.", 1000),  # 1000 words > max 800
    ])

    chunks = chunk_chapter(chapter, max_words=800)

    assert len(chunks) == 1
    assert chunks[0].block_indices == [0]


def test_context_empty_for_first_chunk():
    """첫 번째 청크의 context는 빈 문자열."""
    chapter = make_chapter([("First para.", 5)])

    chunks = chunk_chapter(chapter, max_words=800)

    assert chunks[0].context == ""


def test_context_set_for_second_chunk():
    """두 번째 청크의 context가 비어 있지 않음 (이전 청크 마지막 문장 포함)."""
    chapter = make_chapter([
        ("First sentence. Second sentence.", 500),
        ("Third paragraph here.", 500),
    ])

    chunks = chunk_chapter(chapter, max_words=800)

    assert len(chunks) == 2
    assert chunks[1].context != ""
