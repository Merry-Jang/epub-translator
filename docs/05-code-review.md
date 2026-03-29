# 코드 리뷰 — kindle-translator

## 평가 요약

**수정 필요** — 2개의 필수 버그 수정 후 배포 가능.

전반적으로 높은 코드 품질. 체크포인트, 에러 처리, atomic write, tqdm 진행률 표시 등 견고하게 구현됨. 이전 설계 리뷰에서 지적한 블로커 3개가 모두 반영되었으나, 빈 문자열 처리 로직에서 연쇄 버그가 존재한다.

---

## 이전 블로커 반영 확인

| 블로커 | 파일 | 반영 여부 |
|--------|------|----------|
| 번역 결과 → TextBlock 매핑 로직 | `translate.py:33-100` (`_map_translation_to_blocks`, `_build_translated_chapters`) | ✅ 반영 |
| 실패 청크 fallback 처리 | `epub_builder.py:77-89` (`chapter_translations.get(block_index, None)`) | ✅ 반영 |
| 체크포인트 디렉토리 자동 생성 | `checkpoint.py:21` (`path.parent.mkdir(parents=True, exist_ok=True)`) | ✅ 반영 |

---

## 파일별 리뷰

### `translate.py`

- **[L62-63] 버그**: `_map_translation_to_blocks()` 에서 문단 불일치 시 나머지 블록에 빈 문자열 `""` 할당

  ```python
  result[chunk.block_indices[0]] = translated_text
  for block_index in chunk.block_indices[1:]:
      result[block_index] = ""  # ← 문제
  ```

  `epub_builder.py:78`에서 `translated_text is not None` 조건이 빈 문자열도 `True`로 처리하므로, `element.clear()`가 실행되어 원본 블록 내용이 완전히 지워진다. 독자에게는 빈 문단으로 보인다. 의도는 원문 유지여야 하나, 실제로는 원문 삭제가 발생한다.

  **수정 방법**: `None`을 사용하거나 `epub_builder.py`에서 빈 문자열을 fallback으로 처리:
  ```python
  # 방법 A: _map_translation_to_blocks에서 None 사용
  for block_index in chunk.block_indices[1:]:
      result[block_index] = None  # fallback 신호

  # 방법 B: epub_builder.py 조건 변경 (더 간단)
  if translated_text:  # None과 "" 모두 fallback
      ...
  ```

- **[L212-216] 버그**: `run_pipeline()`에 `endpoint` 파라미터가 없어 `translate_chunk()` 호출 시 하드코딩됨

  ```python
  translated_text = translate_chunk(
      chunk=chunk,
      model=model,
      endpoint="http://localhost:8080/v1",  # 하드코딩
  )
  ```

  `main()`에서 `endpoint = "http://localhost:8080/v1"` 변수를 정의하고 `_check_server(endpoint)`에 전달하지만, `run_pipeline()`에는 전달하지 않는다. 서버 포트가 달라지면 연결 확인은 성공하고 번역 요청은 실패하는 상황이 발생한다.

  **수정 방법**: `run_pipeline()`에 `endpoint: str` 파라미터 추가, `main()`에서 전달.

- **[L34] 개선**: `_map_translation_to_blocks()` `chunk` 파라미터 타입 힌트 누락

  ```python
  def _map_translation_to_blocks(translated_text: str, chunk) -> dict[int, str]:
  ```
  → `chunk: Chunk` 추가 권장.

- **[L197] 경미**: `tqdm(initial=completed)` — resume 시 `completed` 값이 체크포인트 기준이고 `total_chunks`는 현재 재계산 값이라 max_words 변경 시 진행률 표시가 틀릴 수 있음. 기능에는 영향 없음.

### `src/epub_builder.py`

- **[L61-67] 개선**: `_is_excluded()` 로직을 `epub_parser._is_excluded()`를 재사용하지 않고 4줄 중복 구현

  ```python
  # 현재
  is_excluded = False
  for parent in element.parents:
      if parent.name in EXCLUDE_PARENTS:
          is_excluded = True
          break
  if is_excluded:
      continue

  # 개선
  from src.epub_parser import _is_excluded
  if _is_excluded(element):
      continue
  ```

  `BLOCK_TAGS`, `EXCLUDE_PARENTS`는 `epub_parser`에서 import하고 있으면서 `_is_excluded()` 함수는 재사용하지 않아 일관성이 없다.

- **[L93-94] 주의**: `str(soup)` 직렬화 시 XML 선언 및 DOCTYPE 손실 가능

  ```python
  modified_content = str(soup).encode("utf-8")
  ```

  `html.parser` 사용 시 XHTML의 `<?xml version="1.0"?>`, DOCTYPE, 자기 닫는 태그(`<br/>` → `<br>`) 등이 변경될 수 있다. 이것이 일부 EPUB 뷰어에서 렌더링 오류로 이어질 수 있다. 실제 테스트 필요.

### `src/translator.py`

- **[L69] 개선**: OpenAI 클라이언트를 매 청크마다 새로 생성

  ```python
  def translate_chunk(...):
      client = OpenAI(base_url=endpoint, api_key="not-needed")
  ```

  수백 개 청크를 번역할 때 HTTP 연결 풀이 매번 재생성된다. 모듈 레벨 또는 `run_pipeline()` 수준에서 클라이언트를 한 번만 생성하고 파라미터로 전달하는 방식이 효율적이다.

### `src/checkpoint.py`

- 구현 견고. 설계서 대비 100% 일치.
- Atomic write (`tempfile.mkstemp` + `os.replace`) 정확히 구현됨.
- 예외 시 임시 파일 정리(`os.unlink`) 처리됨.

### `src/epub_parser.py`

- 설계서 대비 완전 구현. 특이사항 없음.
- `ignore_ncx` 옵션이 ebooklib 공식 지원 여부 불명확하나 실제 동작에 영향 없을 것으로 판단.

### `src/chunker.py`

- 설계서 대비 완전 구현. 분할 로직 정확.
- `_extract_last_sentences()` 정규식 기반 문장 분리는 설계 리뷰에서 [선택] v2로 분류되었으므로 현재 구현 수용.

---

## 설계 준수 여부

| 설계 항목 | 구현 여부 | 비고 |
|-----------|----------|------|
| EPUB 파싱 → Chapter 리스트 | ✅ | `epub_parser.py` |
| TextBlock → Chunk 분할 | ✅ | `chunker.py` |
| Chunk → 번역 (exponential backoff) | ✅ | `translator.py` |
| Atomic write 체크포인트 | ✅ | `checkpoint.py` |
| 번역 → EPUB 재조립 + fallback | ✅ | `epub_builder.py` |
| CLI (argparse + --resume) | ✅ | `translate.py` |
| MLX-LM 서버 health check | ✅ | `_check_server()` |
| max_words 변경 경고 | ✅ | `translate.py:183-190` |
| 출력 경로 자동 생성 | ✅ | `translate.py:124` |
| `endpoint` 파라미터 일관성 | ❌ | `run_pipeline()`에 미전달 |

---

## 보안 체크

- [x] SQL 인젝션 — 해당 없음
- [x] XSS — 해당 없음
- [x] 하드코딩된 시크릿 — 없음 (MLX-LM은 API 키 불필요)
- [x] 파일 경로 traversal — `pathlib.Path` 사용으로 기본 방어됨
- [x] 파일 덮어쓰기 — 경고 메시지 출력 (로컬 도구 기준 수용 가능)
- [ ] `httpx` 의존성 — `requirements.txt`에 누락 가능성 (확인 필요)

---

## 수정 요청 (반드시 고쳐야 할 항목)

### 수정 1: 빈 문자열 fallback 처리 (`epub_builder.py:78`)

```python
# 현재 (버그)
if translated_text is not None:

# 수정
if translated_text:  # None과 "" 모두 원문 유지
```

이 한 줄 변경으로 문단 불일치 시 나머지 블록 원문 삭제 버그 해결.

### 수정 2: `endpoint` 파라미터 전달 (`translate.py`)

```python
# run_pipeline() 시그니처에 추가
def run_pipeline(
    input_path: str,
    output_path: str,
    model: str,
    checkpoint_path: str,
    resume: bool,
    max_words: int,
    endpoint: str = "http://localhost:8080/v1",  # 추가
) -> None:

# translate_chunk() 호출 수정
translated_text = translate_chunk(
    chunk=chunk,
    model=model,
    endpoint=endpoint,  # 파라미터 사용
)

# main()에서 전달
run_pipeline(
    ...
    endpoint=endpoint,
)
```

---

## Gemini 리뷰 의견

Gemini(gemini-2.5-flash)가 동일 코드를 리뷰한 결과:

**Gemini 주요 지적:**
1. `_map_translation_to_blocks()` 문단 불일치 처리 — "로직 불일치 가능성"으로 지적했으나, `epub_builder.py`의 빈 문자열 처리까지 연결해서 버그로 판단하지는 않음
2. `epub_builder.py`의 `_is_excluded()` 중복 — Sonnet과 동일하게 지적
3. `endpoint` 하드코딩 — Sonnet과 동일하게 지적
4. 빈 `translated_text` 처리 — **"의도적 처리로 수용 가능"으로 해석** (Sonnet과 다른 판단)

**모델 간 의견 차이: 빈 문자열 처리**

| 관점 | Sonnet | Gemini | 최종 판단 |
|------|--------|--------|----------|
| `translated_text = ""` 처리 | **버그** — 원문 삭제됨 | 의도적 빈 교체로 수용 | **Sonnet 판단 채택** |

Gemini는 LLM이 빈 문자열을 직접 반환한 경우를 가정했으나, 실제 원인은 `_map_translation_to_blocks()`에서 인위적으로 `""`를 할당하는 것이다. 이 경우 원문 보존이 올바른 동작이므로 버그로 분류.

| 관점 | Sonnet | Gemini | 최종 판단 |
|------|--------|--------|----------|
| endpoint 하드코딩 | 버그 | 동일 지적 | **버그 (수정 필요)** |
| `_is_excluded()` 중복 | 개선 | 동일 지적 | **권장 수정** |
| 코드 전반 품질 | 높음 | "프로덕션에 가까운 품질" | **합의** |
