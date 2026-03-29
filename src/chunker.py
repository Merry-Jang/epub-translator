"""청크 분할 모듈 — TextBlock을 max_words 기준으로 그룹화."""

import logging
import re
from dataclasses import dataclass, field

from src.epub_parser import Chapter

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """번역 단위 — 1개 이상의 TextBlock 묶음."""
    id: str             # "ch01_chunk00"
    chapter_id: str     # 소속 챕터 ID
    text: str           # 번역할 텍스트 (문단 간 \n\n 구분)
    context: str        # 이전 컨텍스트 (직전 2문장)
    block_indices: list[int] = field(default_factory=list)


def _extract_last_sentences(text: str, n: int = 2) -> str:
    """텍스트에서 마지막 n개 문장을 추출한다 (컨텍스트용)."""
    # HTML 태그 제거
    from bs4 import BeautifulSoup
    plain = BeautifulSoup(text, "html.parser").get_text()

    # 문장 분리: 마침표/물음표/느낌표 + 공백 또는 끝
    sentences = re.split(r'(?<=[.!?])\s+', plain.strip())
    # 빈 문장 제거
    sentences = [s for s in sentences if s.strip()]

    if not sentences:
        return ""

    last_n = sentences[-n:] if len(sentences) >= n else sentences
    return " ".join(last_n)


def chunk_chapter(chapter: Chapter, max_words: int = 800) -> list[Chunk]:
    """
    챕터의 TextBlock들을 max_words 이하의 Chunk로 분할한다.

    분할 규칙:
    1. TextBlock을 순서대로 누적하며 word_count 합산
    2. 누적 합이 max_words를 초과하면 현재까지를 하나의 Chunk로 확정
    3. 단일 TextBlock이 max_words 초과 시 → 그 블록만으로 1개 Chunk
    4. 각 Chunk에 이전 Chunk 마지막 2문장을 context로 첨부
    """
    if not chapter.text_blocks:
        return []

    chunks = []
    chunk_index = 0
    current_blocks = []
    current_word_count = 0
    prev_context = ""

    for block in chapter.text_blocks:
        # 현재 블록을 추가하면 초과하는지 확인
        if current_blocks and current_word_count + block.word_count > max_words:
            # 현재까지 모은 블록들로 Chunk 생성
            chunk = _create_chunk(
                chapter.id, chunk_index, current_blocks, prev_context
            )
            chunks.append(chunk)

            # 다음 컨텍스트 업데이트
            prev_context = _extract_last_sentences(chunk.text)
            chunk_index += 1
            current_blocks = []
            current_word_count = 0

        current_blocks.append(block)
        current_word_count += block.word_count

    # 마지막 남은 블록들
    if current_blocks:
        chunk = _create_chunk(
            chapter.id, chunk_index, current_blocks, prev_context
        )
        chunks.append(chunk)

    logger.debug("챕터 %s: %d 블록 → %d 청크", chapter.id, len(chapter.text_blocks), len(chunks))
    return chunks


def _create_chunk(
    chapter_id: str,
    chunk_index: int,
    blocks: list,
    context: str,
) -> Chunk:
    """블록 리스트로부터 Chunk 객체를 생성한다."""
    chunk_id = f"{chapter_id}_chunk{chunk_index:02d}"
    text = "\n\n".join(b.text for b in blocks)
    block_indices = [b.index for b in blocks]

    return Chunk(
        id=chunk_id,
        chapter_id=chapter_id,
        text=text,
        context=context,
        block_indices=block_indices,
    )
