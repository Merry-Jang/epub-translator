"""번역 모듈 — LLM API 호출 + 재시도 로직."""

import logging
import re
import time

from src.chunker import Chunk
from src.providers import LLMClient

logger = logging.getLogger(__name__)

# 기본 규칙 (모든 문체 공통)
_BASE_RULES = """Rules:
1. Translate accurately while maintaining natural Korean flow
2. Preserve all HTML tags exactly as they appear (<b>, <i>, <a>, etc.) — never add, remove, or modify tags
3. Keep proper nouns (person names, place names) in their original English form
4. Maintain the same number of paragraphs as the input — use blank lines between paragraphs
5. Output ONLY the Korean translation — no explanations, notes, commentary, or preamble like "Here is the translation:"
6. For technical terms, use the common Korean translation with the original in parentheses on first occurrence
7. Never leave entire sentences untranslated — if unsure, translate to the best approximation
8. Do not merge or split paragraphs — input has N paragraphs, output must have exactly N paragraphs
9. Translate idioms and expressions to natural Korean equivalents, not word-for-word"""

# 문체 프리셋
STYLE_PRESETS: dict[str, dict[str, str]] = {
    "default": {
        "name": "기본",
        "persona": "You are a professional English-to-Korean book translator.",
        "style": "",
    },
    "novel": {
        "name": "소설/문학",
        "persona": "You are a literary translator specializing in fiction and novels.",
        "style": (
            "7. Use literary, expressive Korean — convey emotions, atmosphere, and imagery vividly\n"
            "8. Vary sentence length and rhythm for dramatic effect\n"
            "9. Translate dialogue naturally as spoken Korean, reflecting character voice"
        ),
    },
    "science": {
        "name": "과학/논문",
        "persona": "You are a scientific translator specializing in academic and technical texts.",
        "style": (
            "7. Use precise, concise language — prioritize accuracy over style\n"
            "8. Keep all technical terms, units, formulas, and citations intact\n"
            "9. Use formal academic Korean (합니다체)"
        ),
    },
    "philosophy": {
        "name": "철학/인문",
        "persona": "You are a humanities translator specializing in philosophy and critical thought.",
        "style": (
            "7. Preserve the depth and nuance of abstract concepts\n"
            "8. Use contemplative, measured Korean — maintain the author's intellectual tone\n"
            "9. Translate key philosophical terms consistently throughout"
        ),
    },
    "business": {
        "name": "비즈니스",
        "persona": "You are a business translator specializing in corporate and management texts.",
        "style": (
            "7. Use clear, professional Korean — direct and actionable\n"
            "8. Keep business jargon with Korean equivalents (ROI → 투자수익률(ROI))\n"
            "9. Maintain a confident, authoritative tone"
        ),
    },
    "youth": {
        "name": "아동/청소년",
        "persona": "You are a translator specializing in children's and young adult literature.",
        "style": (
            "7. Use simple, friendly Korean that young readers can easily understand\n"
            "8. Avoid complex sentence structures — prefer short, clear sentences\n"
            "9. Make descriptions fun and engaging"
        ),
    },
    "essay": {
        "name": "에세이",
        "persona": "You are a translator specializing in personal essays and creative nonfiction.",
        "style": (
            "7. Use warm, conversational Korean — as if speaking to a friend\n"
            "8. Preserve the author's personal voice and humor\n"
            "9. Keep the relaxed, reflective tone of the original"
        ),
    },
}


def get_system_prompt(style: str = "default") -> str:
    """문체 프리셋에 따른 시스템 프롬프트를 생성한다."""
    preset = STYLE_PRESETS.get(style, STYLE_PRESETS["default"])
    parts = [preset["persona"], "", _BASE_RULES]
    if preset["style"]:
        parts.append(preset["style"])
    return "\n".join(parts)


# 하위 호환용
SYSTEM_PROMPT = get_system_prompt("default")

USER_PROMPT_TEMPLATE = """{context_block}Translate the following English text to Korean.
Each paragraph is separated by a blank line. Preserve the exact same paragraph count and structure.
Do NOT add any prefix like "Here is the translation" — start directly with the Korean text.

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
    style: str = "default",
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

    user_message = USER_PROMPT_TEMPLATE.format(
        context_block=context_block,
        chunk_text=chunk.text,
    )

    messages = [
        {"role": "system", "content": get_system_prompt(style)},
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

            # 응답 잘림 → max_tokens 늘려서 재시도
            if result_obj.finish_reason == "length":
                if max_tokens < 65536:
                    new_max = min(max_tokens * 2, 65536)
                    logger.warning("Chunk %s 응답 잘림 — max_tokens %d→%d로 재시도",
                                   chunk.id, max_tokens, new_max)
                    max_tokens = new_max
                    continue
                else:
                    logger.warning("Chunk %s 응답 잘림 (max_tokens=%d, 더 이상 증가 불가)",
                                   chunk.id, max_tokens)

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
