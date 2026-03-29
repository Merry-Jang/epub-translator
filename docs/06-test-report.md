# 테스트 리포트

## 테스트 요약

| 항목 | 값 |
|------|-----|
| 전체 | 36개 |
| 통과 | 35개 |
| 실패 | 1개 |
| 건너뜀 | 0개 |
| 실행 시간 | 0.31s |
| Python | 3.12.11 |
| pytest | 9.0.2 |

---

## 테스트 항목

### test_checkpoint.py (8/8 PASS)

| 테스트명 | 유형 | 결과 | 비고 |
|---------|------|------|------|
| test_save_and_load_basic | 단위 | PASS | 저장/로드 왕복 |
| test_save_creates_directory | 단위 | PASS | 중첩 디렉토리 자동 생성 |
| test_atomic_write_no_leftover_tmp | 단위 | PASS | .tmp 잔류 파일 없음 |
| test_save_overwrites_existing | 단위 | PASS | 덮어쓰기 정상 |
| test_load_missing_file_returns_none | 단위 | PASS | 파일 없음 → None |
| test_load_corrupted_json_returns_none | 단위 | PASS | 손상된 JSON → None |
| test_save_and_load_unicode | 단위 | PASS | 한국어 유니코드 보존 |
| test_load_empty_file_returns_none | 단위 | PASS | 빈 파일 → None |

### test_chunker.py (11/11 PASS)

| 테스트명 | 유형 | 결과 | 비고 |
|---------|------|------|------|
| test_short_text_single_chunk | 단위 | PASS | max_words 미만 → 청크 1개 |
| test_long_text_multiple_chunks | 단위 | PASS | 1000 words → 2 청크 |
| test_empty_blocks_returns_empty_list | 단위 | PASS | 빈 블록 → [] |
| test_block_indices_single_chunk | 단위 | PASS | indices = [0, 1, 2] |
| test_block_indices_multiple_chunks | 단위 | PASS | 모든 인덱스 연속 |
| test_chunk_text_joined_by_double_newline | 단위 | PASS | \n\n 조인 확인 |
| test_chunk_id_format | 단위 | PASS | ch00_chunk00 형식 |
| test_chunk_id_increments | 단위 | PASS | chunk00, chunk01 순증 |
| test_single_block_exceeds_max_words_still_one_chunk | 단위 | PASS | 규칙 3: 단일 초과 블록 허용 |
| test_context_empty_for_first_chunk | 단위 | PASS | 첫 청크 context = "" |
| test_context_set_for_second_chunk | 단위 | PASS | 두 번째 청크 context 비어 있지 않음 |

### test_epub_builder.py (7/7 PASS)

| 테스트명 | 유형 | 결과 | 비고 |
|---------|------|------|------|
| test_translated_text_replaces_block | 단위 | PASS | 번역 텍스트 HTML 교체 |
| test_empty_string_translation_keeps_original | 단위 | PASS | "" → 원문 유지 (버그 수정 확인) |
| test_missing_block_index_keeps_original | 단위 | PASS | 키 없음 → 원문 유지 |
| test_fallback_count_logged_correctly | 단위 | PASS | 미번역 2개 → WARNING 2건 |
| test_multiple_blocks_all_translated | 단위 | PASS | 전체 번역 정상 |
| test_language_set_to_ko | 단위 | PASS | set_language("ko") 호출 확인 |
| test_non_document_item_skipped | 단위 | PASS | 이미지 타입 아이템 스킵 |

### test_translator.py (9/10, 1 FAIL)

| 테스트명 | 유형 | 결과 | 비고 |
|---------|------|------|------|
| test_normal_response_returns_translation | 단위 | PASS | 정상 응답 반환 |
| test_response_whitespace_stripped | 단위 | PASS | 전후 공백 strip() |
| **test_think_tags_removed** | 단위 | **FAIL** | `<think>` 태그 미제거 — 아래 분석 참조 |
| test_retry_on_api_exception | 단위 | PASS | 2회 실패 후 3번째 성공 |
| test_max_retries_exceeded_raises_translation_error | 단위 | PASS | TranslationError 발생 |
| test_empty_response_retries_then_raises | 단위 | PASS | 빈 응답 3회 → TranslationError |
| test_whitespace_only_response_retries | 단위 | PASS | 공백 응답 → 재시도 |
| test_context_included_in_prompt | 단위 | PASS | [CONTEXT] 블록 포함 |
| test_no_context_no_context_block | 단위 | PASS | context 없으면 [CONTEXT] 미포함 |
| test_translation_error_has_chunk_id | 단위 | PASS | 에러에 chunk_id, retry_count 포함 |

---

## 실패 분석

### `test_think_tags_removed` — FAIL

**에러 메시지:**
```
AssertionError: assert '<think>' not in '<think>internal reasoning here</think>번역 결과'
```

**원인:**
`translator.py`의 `translate_chunk()`가 API 응답에서 `<think>...</think>` 태그를 제거하지 않는다.
현재 코드는 `result.strip()`만 적용하며 태그 제거 로직이 없다.

Qwen3 모델은 `/no_think` 지시어로 thinking 모드를 비활성화하지만, 모델이 이를 무시하거나 오작동 시 태그가 응답에 포함될 수 있다.

**수정 제안 (translator.py):**
```python
import re

# translate_chunk() 내 result 반환 직전에 추가:
result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
```

**영향도:** 낮음 — `/no_think`가 정상 동작하면 실제 발생하지 않음. 방어 코드 추가 권장.

---

## 커버리지

| 모듈 | 핵심 로직 | 테스트 커버 |
|------|-----------|------------|
| `checkpoint.py` | save/load, atomic write, 에러 처리 | 완전 |
| `chunker.py` | 분할 규칙 1~4, context, chunk id | 완전 |
| `epub_builder.py` | 교체, fallback, 언어 설정 | 완전 (epub 파싱 제외, mock) |
| `translator.py` | 정상 응답, 재시도, 에러 | 완전 (`<think>` 제거 제외) |
| `epub_parser.py` | — | 미테스트 (실제 EPUB 파일 필요) |

**미테스트 항목:**
- `epub_parser.parse_epub()` — 실제 EPUB 파일 픽스처 필요
- translator의 `<think>` 태그 제거 — 구현 자체가 누락됨

---

## 최종 판정

**수정 필요** — 단, 블로커 아님

- 35/36 테스트 통과 (97.2%)
- 실패 1건은 방어 코드 누락(`<think>` 태그 미제거)으로 실제 프로덕션 영향 낮음
- `<think>` 태그 제거 로직 추가 후 재배포 권장
