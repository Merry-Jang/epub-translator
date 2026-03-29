"""EPUB 빌더 모듈 — 원본 EPUB + 번역 텍스트 → 새 EPUB 생성."""

import logging

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from src.epub_parser import BLOCK_TAGS, EXCLUDE_PARENTS

logger = logging.getLogger(__name__)


def build_epub(
    original_path: str,
    translated_chapters: dict[str, dict[int, str]],
    output_path: str,
) -> None:
    """
    원본 EPUB의 구조를 유지하면서 번역된 텍스트로 교체한 새 EPUB을 생성한다.

    1. 원본 EPUB 로드
    2. 각 챕터 XHTML의 블록 요소를 번역문으로 교체
    3. 번역이 없는 블록은 원문 유지 (fallback)
    4. dc:language를 'ko'로 변경
    5. 이미지/CSS/폰트는 원본 그대로 복사
    """
    book = epub.read_epub(original_path, options={"ignore_ncx": True})

    # spine 순서 가져오기
    spine_ids = [item_id for item_id, _ in book.spine]

    # item id → item 매핑
    items_by_id = {}
    for item in book.get_items():
        items_by_id[item.get_id()] = item

    total_blocks = 0
    translated_count = 0
    fallback_count = 0
    chapter_index = 0

    for item_id in spine_ids:
        item = items_by_id.get(item_id)
        if item is None:
            continue

        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue

        chapter_id = f"ch{chapter_index:02d}"
        chapter_translations = translated_chapters.get(chapter_id, {})

        content = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(content, "html.parser")

        # 블록 요소 순회
        block_index = 0
        for element in soup.find_all(BLOCK_TAGS):
            # 제외 대상 부모 안에 있으면 스킵
            is_excluded = False
            for parent in element.parents:
                if parent.name in EXCLUDE_PARENTS:
                    is_excluded = True
                    break
            if is_excluded:
                continue

            # 빈 블록 스킵
            plain_text = element.get_text(strip=True)
            if not plain_text:
                continue

            total_blocks += 1

            # 번역문이 있으면 교체
            translated_text = chapter_translations.get(block_index, None)
            if translated_text is not None:
                element.clear()
                # 번역된 HTML 삽입
                translated_soup = BeautifulSoup(translated_text, "html.parser")
                for child in list(translated_soup.children):
                    element.append(child)
                translated_count += 1
            else:
                # 원문 유지 (fallback)
                logger.warning("WARNING: Block %s[%d] not translated, keeping original",
                               chapter_id, block_index)
                fallback_count += 1

            block_index += 1

        # 수정된 XHTML을 item에 반영
        modified_content = str(soup).encode("utf-8")
        item.set_content(modified_content)

        chapter_index += 1

    # dc:language 메타데이터를 'ko'로 변경
    book.set_language("ko")

    # 새 EPUB 저장
    epub.write_epub(output_path, book)

    logger.info("EPUB 빌드 완료: %s", output_path)
    logger.info("  번역된 블록: %d / %d", translated_count, total_blocks)
    if fallback_count > 0:
        logger.info("  원문 유지 (fallback): %d", fallback_count)
