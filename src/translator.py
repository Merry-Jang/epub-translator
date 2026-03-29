"""번역 모듈 — LLM API 호출 + 재시도 로직."""

import logging
import re
import time

from src.chunker import Chunk
from src.providers import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a professional English-to-Korean book translator.

Rules:
1. Translate accurately while maintaining natural Korean flow
2. Preserve all HTML tags exactly as they appear (<b>, <i>, <a>, etc.)
3. Keep proper nouns (person names, place names) in their original English form
4. Maintain the same number of paragraphs as the input — use blank lines between paragraphs
5. Output ONLY the Korean translation — no explanations, notes, or commentary
6. For technical terms, use the common Korean translation with the original in parentheses on first occurrence"""

# Local Qwen 전용: thinking 모드 비활성화
USER_PROMPT_TEMPLATE_LOCAL = """/no_think

{context_block}Translate the following English text to Korean.
Each paragraph is separated by a blank line. Preserve the same paragraph structure.

[TEXT]
{chunk_text}
[/TEXT]"""

# OpenAI / Claude 용
USER_PROMPT_TEMPLATE_CLOUD = """{context_block}Translate the following English text to Korean.
Each paragraph is separated by a blank line. Preserve the same paragraph structure.

[TEXT]
{chunk_text}
[/TEXT]"""

CONTEXT_BLOCK_TEMPLATE = """[CONTEXT — for reference only, do NOT translate this]
{context}
[/CONTEXT]

"""


class TranslationError(Exception):
    """번역 실패 예외."""
    def __init__(self, chunk_id: str, message: str, retry_count: int):
        self.chunk_id = chunk_id
        self.retry_count = retry_count
        super().__init__(f"Chunk {chunk_id}: {message} (retries: {retry_count})")


def translate_chunk(
    chunk: Chunk,
    client: LLMClient,
    model: str,
    temperature: float = 0.1,
    top_p: float = 0.3,
    max_tokens: int = 16384,
    max_retries: int = 3,
) -> str:
    """
    하나의 Chunk를 LLM API로 번역한다.

    1. 프롬프트 조립 (프로바이더별 템플릿 선택)
    2. LLMClient.complete() 호출
    3. 실패 시 exponential backoff 재시도
    4. 빈 응답 시 1회 재시도
    5. max_retries 초과 시 TranslationError 발생

    Returns:
        번역된 한국어 텍스트
    Raises:
        TranslationError: 모든 재시도 실패 시
    """
    context_block = ""
    if chunk.context:
        context_block = CONTEXT_BLOCK_TEMPLATE.format(context=chunk.context)

    # 프로바이더별 프롬프트 템플릿 선택
    template = (
        USER_PROMPT_TEMPLATE_LOCAL
        if client.provider == "local"
        else USER_PROMPT_TEMPLATE_CLOUD
    )
    user_message = template.format(
        context_block=context_block,
        chunk_text=chunk.text,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    last_error = None

    for attempt in range(max_retries):
        try:
            result_obj = client.complete(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )

            # 응답 잘림 확인
            if result_obj.finish_reason == "length":
                logger.warning("WARNING: Chunk %s response truncated (finish_reason=length)",
                               chunk.id)

            result = result_obj.content or ""

            # <think> 태그 제거 먼저 (MLX-LM Qwen은 thinking 토큰이 content에 섞일 수 있음)
            result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()

            # 빈 응답 처리
            if not result:
                if attempt < max_retries - 1:
                    logger.warning("빈 응답 — 재시도 %d/%d: %s",
                                   attempt + 1, max_retries, chunk.id)
                    time.sleep(2 ** attempt)
                    continue
                raise TranslationError(chunk.id, "빈 응답 반복", attempt + 1)

            logger.debug("번역 완료: %s (attempt %d)", chunk.id, attempt + 1)
            return result

        except TranslationError:
            raise
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning("API 오류 — %ds 후 재시도 %d/%d: %s — %s",
                               wait, attempt + 1, max_retries, chunk.id, e)
                time.sleep(wait)
            else:
                raise TranslationError(
                    chunk.id,
                    f"API 호출 실패: {last_error}",
                    max_retries,
                )
