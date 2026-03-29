"""EPUB 파싱 모듈 — 챕터/문단 추출."""

import logging
from dataclasses import dataclass, field

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# 번역 대상 블록 태그
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "figcaption"}

# 제외할 부모 태그 — 내부 텍스트를 번역하지 않음
EXCLUDE_PARENTS = {"script", "style", "nav"}


@dataclass
class TextBlock:
    """XHTML 내 번역 가능한 블록 요소 하나."""
    index: int          # 챕터 내 순서 (0-based)
    text: str           # 블록의 inner HTML (인라인 태그 포함)
    tag: str            # 원본 태그 이름
    word_count: int     # 영문 단어 수


@dataclass
class Chapter:
    """EPUB 내 하나의 챕터(문서)."""
    id: str             # "ch00", "ch01", ...
    title: str          # 챕터 제목
    href: str           # EPUB 내부 경로
    content: str        # 원본 XHTML 전체
    text_blocks: list[TextBlock] = field(default_factory=list)


def _is_excluded(element: Tag) -> bool:
    """블록 요소가 제외 대상 부모 안에 있는지 확인한다."""
    for parent in element.parents:
        if parent.name in EXCLUDE_PARENTS:
            return True
    return False


def _get_inner_html(element: Tag) -> str:
    """블록 요소의 inner HTML을 반환한다 (인라인 태그 보존)."""
    return element.decode_contents()


def _count_words(text: str) -> int:
    """영문 기준 단어 수를 센다 (HTML 태그 제거 후)."""
    plain = BeautifulSoup(text, "html.parser").get_text()
    return len(plain.split())


def parse_epub(epub_path: str) -> list[Chapter]:
    """
    EPUB 파일을 파싱하여 챕터 리스트를 반환한다.

    1. EbookLib으로 EPUB 로드
    2. spine 순서대로 문서 순회
    3. 각 문서의 XHTML에서 블록 요소 추출
    4. script, style, nav 내부 텍스트 제외
    5. 빈 블록 제외
    """
    book = epub.read_epub(epub_path, options={"ignore_ncx": True})

    # spine 순서 가져오기
    spine_ids = [item_id for item_id, _ in book.spine]

    # item id → item 매핑
    items_by_id = {}
    for item in book.get_items():
        items_by_id[item.get_id()] = item

    chapters = []
    chapter_index = 0

    for item_id in spine_ids:
        item = items_by_id.get(item_id)
        if item is None:
            continue

        # HTML 문서만 처리
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        content = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        # 챕터 제목 추출: 첫 heading 또는 item id
        title_tag = soup.find(["h1", "h2", "h3"])
        title = title_tag.get_text(strip=True) if title_tag else f"Chapter {chapter_index}"

        # 블록 요소 추출
        text_blocks = []
        block_index = 0

        for element in soup.find_all(BLOCK_TAGS):
            # 제외 대상 부모 안에 있으면 스킵
            if _is_excluded(element):
                continue

            inner_html = _get_inner_html(element)

            # 빈 블록 제외 (공백만 있는 경우)
            plain_text = element.get_text(strip=True)
            if not plain_text:
                continue

            word_count = _count_words(inner_html)

            text_blocks.append(TextBlock(
                index=block_index,
                text=inner_html,
                tag=element.name,
                word_count=word_count,
            ))
            block_index += 1

        chapter_id = f"ch{chapter_index:02d}"
        href = item.get_name()

        chapters.append(Chapter(
            id=chapter_id,
            title=title,
            href=href,
            content=content,
            text_blocks=text_blocks,
        ))

        logger.info("챕터 파싱: %s '%s' — %d 블록, %d 단어",
                     chapter_id, title, len(text_blocks),
                     sum(b.word_count for b in text_blocks))
        chapter_index += 1

    logger.info("EPUB 파싱 완료: %d 챕터, %d 블록",
                len(chapters), sum(len(c.text_blocks) for c in chapters))
    return chapters
