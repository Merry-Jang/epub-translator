"""번역 모듈 단위 테스트 — OpenAI 클라이언트 Mock 기반."""

import re
from unittest.mock import MagicMock, patch

import pytest

from src.chunker import Chunk
from src.translator import translate_chunk, TranslationError


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def make_chunk(
    text: str = "Hello world.",
    context: str = "",
    chunk_id: str = "ch00_chunk00",
) -> Chunk:
    return Chunk(
        id=chunk_id,
        chapter_id="ch00",
        text=text,
        context=context,
        block_indices=[0],
    )


def make_mock_response(content: str, finish_reason: str = "stop") -> MagicMock:
    """Mock OpenAI ChatCompletion response 생성."""
    response = MagicMock()
    response.choices[0].message.content = content
    response.choices[0].finish_reason = finish_reason
    return response


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_normal_response_returns_translation():
    """정상 API 응답 → 번역 텍스트 반환."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = make_mock_response("안녕 세계.")

    result = translate_chunk(make_chunk("Hello world."), mock_client)

    assert result == "안녕 세계."


def test_response_whitespace_stripped():
    """응답 전후 공백/개행 제거."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = make_mock_response("  번역 결과  \n\n")

    result = translate_chunk(make_chunk(), mock_client)

    assert result == "번역 결과"


def test_think_tags_removed():
    """<think>...</think> 태그가 응답에서 제거됨.

    Qwen3 모델이 /no_think 무시하고 thinking 태그를 반환할 경우,
    최종 번역 결과에는 포함되지 않아야 한다.

    NOTE: 현재 구현이 이를 처리하지 않으면 이 테스트는 FAIL → 구현 누락 확인용.
    """
    content_with_think = "<think>internal reasoning here</think>번역 결과"
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = make_mock_response(content_with_think)

    result = translate_chunk(make_chunk(), mock_client)

    assert "<think>" not in result
    assert "</think>" not in result
    assert "번역 결과" in result


def test_retry_on_api_exception():
    """API 예외 → exponential backoff 재시도 후 성공."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        Exception("Connection refused"),
        Exception("Timeout"),
        make_mock_response("번역 성공"),
    ]

    with patch("src.translator.time.sleep"):
        result = translate_chunk(make_chunk(), mock_client, max_retries=3)

    assert result == "번역 성공"
    assert mock_client.chat.completions.create.call_count == 3


def test_max_retries_exceeded_raises_translation_error():
    """max_retries 모두 소진 → TranslationError 발생."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("API unavailable")

    with patch("src.translator.time.sleep"), \
         pytest.raises(TranslationError) as exc_info:
        translate_chunk(make_chunk("Hello.", chunk_id="ch01_chunk03"), mock_client, max_retries=3)

    assert exc_info.value.chunk_id == "ch01_chunk03"
    assert exc_info.value.retry_count == 3


def test_empty_response_retries_then_raises():
    """빈 응답 → max_retries까지 재시도 후 TranslationError."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = make_mock_response("")

    with patch("src.translator.time.sleep"), \
         pytest.raises(TranslationError):
        translate_chunk(make_chunk(), mock_client, max_retries=3)

    assert mock_client.chat.completions.create.call_count == 3


def test_whitespace_only_response_retries():
    """공백만 있는 응답도 빈 응답으로 처리 → 재시도."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        make_mock_response("   \n   "),  # 공백만
        make_mock_response("실제 번역"),
    ]

    with patch("src.translator.time.sleep"):
        result = translate_chunk(make_chunk(), mock_client, max_retries=3)

    assert result == "실제 번역"


def test_context_included_in_prompt():
    """context가 있으면 user 메시지에 [CONTEXT] 블록 포함."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = make_mock_response("번역")

    chunk = make_chunk("New paragraph.", context="Previous sentence. Another one.")
    translate_chunk(chunk, mock_client)

    messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in messages if m["role"] == "user")

    assert "[CONTEXT" in user_content
    assert "Previous sentence" in user_content


def test_no_context_no_context_block():
    """context가 비어 있으면 [CONTEXT] 블록이 포함되지 않음."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = make_mock_response("번역")

    chunk = make_chunk("Some text.", context="")
    translate_chunk(chunk, mock_client)

    messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    user_content = next(m["content"] for m in messages if m["role"] == "user")

    assert "[CONTEXT" not in user_content


def test_translation_error_has_chunk_id():
    """TranslationError에 chunk_id와 retry_count 포함."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("fail")

    with patch("src.translator.time.sleep"), \
         pytest.raises(TranslationError) as exc_info:
        translate_chunk(
            make_chunk(chunk_id="ch02_chunk05"),
            mock_client,
            max_retries=2,
        )

    err = exc_info.value
    assert err.chunk_id == "ch02_chunk05"
    assert err.retry_count == 2
    assert "ch02_chunk05" in str(err)
