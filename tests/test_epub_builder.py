"""EPUB 빌더 단위 테스트 — epub 라이브러리를 Mock으로 대체."""

import logging
from unittest.mock import MagicMock, patch

import ebooklib
import pytest
from bs4 import BeautifulSoup

from src.epub_builder import build_epub


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def make_mock_item(item_id: str, html_content: str):
    """ITEM_DOCUMENT 타입 Mock EPUB 아이템 생성."""
    item = MagicMock()
    item.get_id.return_value = item_id
    item.get_type.return_value = ebooklib.ITEM_DOCUMENT
    item.get_content.return_value = html_content.encode("utf-8")
    item.get_name.return_value = f"{item_id}.xhtml"
    return item


def run_build(mock_item, translations: dict, *, spine_id: str = "ch1") -> str:
    """build_epub을 실행하고 set_content에 전달된 HTML을 반환."""
    mock_book = MagicMock()
    mock_book.spine = [(spine_id, None)]
    mock_book.get_items.return_value = [mock_item]

    with patch("src.epub_builder.epub.read_epub", return_value=mock_book), \
         patch("src.epub_builder.epub.write_epub"):
        build_epub(
            original_path="input.epub",
            translated_chapters={"ch00": translations},
            output_path="output.epub",
        )

    return mock_item.set_content.call_args[0][0].decode("utf-8")


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_translated_text_replaces_block():
    """번역 텍스트가 있으면 HTML 블록 내용이 번역문으로 교체됨."""
    html = "<html><body><p>Hello world</p></body></html>"
    mock_item = make_mock_item("ch1", html)

    saved = run_build(mock_item, {0: "안녕 세계"})

    soup = BeautifulSoup(saved, "html.parser")
    assert soup.find("p").get_text() == "안녕 세계"


def test_empty_string_translation_keeps_original():
    """translated_text = '' → 원문 유지 (빈 문자열 버그 수정 검증)."""
    html = "<html><body><p>Original text</p></body></html>"
    mock_item = make_mock_item("ch1", html)

    saved = run_build(mock_item, {0: ""})  # 빈 문자열

    soup = BeautifulSoup(saved, "html.parser")
    assert soup.find("p").get_text() == "Original text"


def test_missing_block_index_keeps_original():
    """block_index에 번역 없음 (키 없음 → None) → 원문 유지."""
    html = "<html><body><p>Original text</p></body></html>"
    mock_item = make_mock_item("ch1", html)

    saved = run_build(mock_item, {})  # 번역 dict 비어 있음

    soup = BeautifulSoup(saved, "html.parser")
    assert soup.find("p").get_text() == "Original text"


def test_fallback_count_logged_correctly(caplog):
    """번역 없는 블록 수만큼 WARNING 로그가 기록됨."""
    html = """<html><body>
        <p>Para 1</p>
        <p>Para 2</p>
        <p>Para 3</p>
    </body></html>"""
    mock_item = make_mock_item("ch1", html)
    mock_book = MagicMock()
    mock_book.spine = [("ch1", None)]
    mock_book.get_items.return_value = [mock_item]

    with caplog.at_level(logging.WARNING), \
         patch("src.epub_builder.epub.read_epub", return_value=mock_book), \
         patch("src.epub_builder.epub.write_epub"):
        build_epub(
            original_path="input.epub",
            translated_chapters={"ch00": {0: "번역됨"}},  # block 1, 2 번역 없음
            output_path="output.epub",
        )

    fallback_warnings = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "not translated" in r.message
    ]
    assert len(fallback_warnings) == 2


def test_multiple_blocks_all_translated():
    """모든 블록에 번역 있음 → 모두 교체, fallback 없음."""
    html = "<html><body><p>Para A</p><p>Para B</p></body></html>"
    mock_item = make_mock_item("ch1", html)

    saved = run_build(mock_item, {0: "문단 A", 1: "문단 B"})

    soup = BeautifulSoup(saved, "html.parser")
    paragraphs = soup.find_all("p")
    assert paragraphs[0].get_text() == "문단 A"
    assert paragraphs[1].get_text() == "문단 B"


def test_language_set_to_ko():
    """출력 EPUB의 dc:language = 'ko'로 설정됨."""
    html = "<html><body><p>Hello</p></body></html>"
    mock_item = make_mock_item("ch1", html)
    mock_book = MagicMock()
    mock_book.spine = [("ch1", None)]
    mock_book.get_items.return_value = [mock_item]

    with patch("src.epub_builder.epub.read_epub", return_value=mock_book), \
         patch("src.epub_builder.epub.write_epub"):
        build_epub(
            original_path="input.epub",
            translated_chapters={"ch00": {0: "안녕"}},
            output_path="output.epub",
        )

    mock_book.set_language.assert_called_once_with("ko")


def test_non_document_item_skipped():
    """ITEM_DOCUMENT 타입이 아닌 아이템은 처리 건너뜀."""
    html = "<html><body><p>Should not change</p></body></html>"
    mock_item = make_mock_item("ch1", html)
    mock_item.get_type.return_value = ebooklib.ITEM_IMAGE  # 이미지 타입

    mock_book = MagicMock()
    mock_book.spine = [("ch1", None)]
    mock_book.get_items.return_value = [mock_item]

    with patch("src.epub_builder.epub.read_epub", return_value=mock_book), \
         patch("src.epub_builder.epub.write_epub"):
        build_epub(
            original_path="input.epub",
            translated_chapters={"ch00": {0: "바뀌면 안 됨"}},
            output_path="output.epub",
        )

    # set_content 호출 안 됨
    mock_item.set_content.assert_not_called()
