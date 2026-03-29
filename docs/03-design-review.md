# 설계 리뷰 — kindle-translator

## 평가 요약

**수정 필요** — 3개의 블로커 항목을 설계서에 명시한 후 구현 가능.

아키텍처 방향은 올바르고 설계 완성도가 높다. 단, 구현 시 혼선을 야기할 수 있는 3가지 핵심 로직이 설계서에 누락되어 있어 수정이 필요하다.

---

## 강점

- **데이터 모델 명확성**: `TextBlock → Chunk → translated` 흐름이 명시적
- **Atomic write 체크포인트**: `tempfile + os.replace()` 방식으로 크래시 안전성 확보
- **에러 처리 전략 실용적**: 실패 청크를 기록하고 계속 진행 → `--resume`으로 재시도
- **순차 처리 선택 근거 명확**: 단일 GPU 인스턴스, 복잡도 대비 이득 없음 → 합리적 판단
- **프롬프트 설계 충분**: `/no_think` + 컨텍스트 블록 분리로 번역 품질 확보
- **구현 순서 가이드**: Step 1~8로 개발 순서와 의존성 명시

---

## 개선 필요

### [필수] 블로커 — 구현 전 반드시 해결

#### 1. 번역 결과 → TextBlock 매핑 로직 누락

**문제**: `translate_chunk()`는 하나의 문자열을 반환하지만, `build_epub()`의 인터페이스는 `translated_chapters: dict[str, dict[int, str]]` (chapter_id → block_index → translated_text)를 요구한다. 청크 내 여러 블록의 번역문을 어떻게 각 block_index에 매핑할지 설계서에 명시가 없다.

**현재 에러 처리 섹션**: "문단 수 불일치 시 전체 번역문을 첫 번째 블록에 합쳐서 배치"라고 언급되었으나, 정상적인 경우의 분할 로직이 없다.

**수정 제안**: `run_pipeline()`에서 번역 결과 문자열을 `\n\n`으로 분리하여 `block_indices` 순서대로 매핑하는 로직을 명시:

```python
# run_pipeline 내부
translated_text = translate_chunk(chunk)  # "번역1\n\n번역2\n\n번역3"
paragraphs = translated_text.split("\n\n")
if len(paragraphs) == len(chunk.block_indices):
    for idx, block_index in enumerate(chunk.block_indices):
        translated_chapters[chunk.chapter_id][block_index] = paragraphs[idx]
else:
    # 불일치: 전체를 첫 번째 블록에 할당, 나머지는 빈 문자열
    translated_chapters[chunk.chapter_id][chunk.block_indices[0]] = translated_text
    for block_index in chunk.block_indices[1:]:
        translated_chapters[chunk.chapter_id][block_index] = ""
```

> **Gemini 동의**: "번역된 청크 문자열을 원래 TextBlock 수만큼의 번역문으로 정확히 분할하고 매핑하는 로직이 명시적으로 누락되어 있음 — 핵심적인 부분"

#### 2. 실패 청크의 `build_epub()` 처리 방법 불명확

**문제**: `translated_chapters` dict에 존재하지 않는 `block_index`를 `build_epub()`에서 만났을 때의 처리가 명시되지 않았다. 번역 실패 시 원문을 유지한다고 언급했지만, 실제 구현 방법이 없다.

**수정 제안**: `build_epub()` 설계에 명시:

```python
# 번역본이 없는 block_index는 원본 inner HTML 유지
translated_text = translated_chapters.get(chapter_id, {}).get(block_index, None)
if translated_text is not None:
    block_element.clear()
    block_element.append(BeautifulSoup(translated_text, "html.parser"))
# else: 원본 그대로 유지 (변경 없음)
```

#### 3. 체크포인트 디렉토리 자동 생성 미명시

**문제**: 기본 체크포인트 경로가 `checkpoints/{input_stem}_progress.json`이지만, `checkpoints/` 디렉토리가 없을 경우 `save_progress()`가 실패한다. `checkpoint.py` 설계에 디렉토리 생성 로직이 없다.

**수정 제안**: `save_progress()` 또는 초기화 단계에서:

```python
Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)
```

---

### [권장] 개선하면 좋은 항목

#### 4. `--resume` 시 `max_words` 변경 충돌

**문제**: `--resume` 시 `max_words`를 다르게 지정하면 chunk_id가 달라져 기존 체크포인트의 완료 상태가 적용되지 않는다. 특히 "긴 청크 처리" 섹션에서 "max_words를 절반으로 줄여 재분할"을 언급했는데, 이렇게 하면 기존 `ch01_chunk01`이 `ch01_chunk01`, `ch01_chunk02`로 분리되어 체크포인트 불일치 발생.

**수정 제안**: 체크포인트 JSON에 `max_words` 값을 저장하고, `--resume` 시 불일치할 경우 경고 출력:

```
WARNING: Checkpoint was created with max_words=800, current value is 400.
Chunk IDs may not match. Use --max-words 800 to resume correctly, or delete checkpoint to restart.
```

#### 5. `translate_chunk()`에 timeout 파라미터 추가

**문제**: OpenAI 클라이언트 기본 timeout은 600초. 네트워크 문제나 MLX-LM 행(hang)이 발생할 경우 10분을 기다리게 된다. 설계서에 timeout 설정이 없다.

**수정 제안**: `translate_chunk()` 파라미터에 `timeout: float = 120.0` 추가, OpenAI 클라이언트 생성 시 반영.

#### 6. 번역 결과 HTML 유효성 검증

**문제**: LLM이 HTML 태그를 100% 보존하리라는 보장이 없다. `<b>text</b>` → `텍스트<b></b>` 또는 태그 누락 등이 발생할 수 있으며, 이 경우 EPUB 뷰어 렌더링 오류로 이어진다. 현재 설계에 검증 로직이 없다.

**수정 제안**: `epub_builder`에서 번역된 HTML 삽입 전 간단한 태그 카운트 비교:

```python
original_tag_count = len(BeautifulSoup(original_html, "html.parser").find_all())
translated_tag_count = len(BeautifulSoup(translated_html, "html.parser").find_all())
if original_tag_count != translated_tag_count:
    logging.warning(f"HTML tag count mismatch in {chapter_id}[{block_index}]: "
                   f"original={original_tag_count}, translated={translated_tag_count}")
```

#### 7. 출력 파일 경로 안전성

**문제**: 출력 경로의 부모 디렉토리가 없거나, 이미 동일 파일이 존재할 경우의 처리가 없다.

**수정 제안**: `run_pipeline()` 시작 시:

```python
output_path = Path(output_path)
output_path.parent.mkdir(parents=True, exist_ok=True)
if output_path.exists():
    logging.warning(f"Output file already exists and will be overwritten: {output_path}")
```

---

### [선택] v2에서 해도 되는 항목

- **번역된 텍스트를 체크포인트 JSON과 분리 저장**: 대형 책은 체크포인트 파일이 수 MB → 매 청크마다 전체 재작성 오버헤드 발생. `checkpoints/{stem}/ch01_chunk00.txt` 별도 저장 방식으로 전환 가능.
- **HTML 블록 태그 범위 확장**: `div`, `section`, `article` 등 비표준 구조를 가진 EPUB 처리. 초기에는 현재 태그 목록으로 충분하나, 실제 킨들 책 테스트 후 필요 시 추가.
- **용어집 파일 지원**: `--glossary glossary.json`으로 도메인 특화 용어 번역 품질 향상.
- **파이프라인 클래스 분리**: `translate.py`의 `run_pipeline()`을 `src/pipeline.py`의 `TranslationPipeline` 클래스로 캡슐화.

---

## 리스크

| 리스크 | 심각도 | 대응 |
|--------|--------|------|
| LLM HTML 태그 손상 | 높음 | 프롬프트 명시 + 간단한 유효성 검증 |
| 청크 경계 문맥 단절 | 중간 | 이전 2문장 컨텍스트로 완화 |
| 대형 책 체크포인트 파일 크기 | 낮음 | 초기 구현에서는 무시, v2에서 개선 |
| `/no_think` 미지원 MLX-LM 버전 | 낮음 | `extra_body` fallback 설계됨 |
| DRM EPUB 식별 불명확 | 낮음 | ebooklib 로드 실패 → 에러 메시지 충분 |

---

## 보안 체크

- [x] SQL 인젝션 — 해당 없음 (DB 미사용)
- [x] XSS — 해당 없음 (웹 미사용)
- [x] 하드코딩된 시크릿 — 없음 (MLX-LM 로컬, API 키 불필요)
- [x] 입력 검증 — CLI에서 파일 존재 여부 확인 명시됨 (EPUB 파싱 실패 처리 있음)
- [ ] 파일 경로 트래버설 — checkpoint_path 및 output_path에 사용자 입력이 직접 사용되므로, 절대 경로 정규화 권장 (낮은 리스크이나 `Path(path).resolve()` 추가 검토)

---

## Gemini 리뷰 의견

Gemini(gemini-2.5-flash)가 동일 설계서를 리뷰한 결과:

**Gemini 추가 지적 (Sonnet과 차별화):**

1. **문장 분리 로직의 복잡성**: `_extract_last_sentences()`에서 축약어(Dr., Mrs.) 등으로 인한 단순 정규식의 한계 → NLTK `punkt` 토크나이저 권장
2. **체크포인트 파일 무결성 검증**: 체크포인트에 source EPUB의 SHA256 해시값 저장, 로드 시 비교하여 EPUB 파일 변경 여부 확인
3. **청크 분할 기준과 토큰 수 불일치**: `max_words`가 영문 단어 수 기반이라 LLM 토큰 수와 차이 발생 → 토크나이저 기반 `max_tokens` 옵션 고려
4. **성능: 체크포인트 저장 빈도**: 매 청크마다 전체 JSON 재작성 → N개 청크 단위 저장 또는 텍스트 별도 파일 저장 권장

**Gemini도 동의한 주요 이슈:**
- 번역 결과 → TextBlock 매핑 로직 누락 (핵심 블로커)
- 실패 청크의 `build_epub()` 처리 불명확
- `max_words` 변경 시 chunk_id 충돌

---

## 모델 간 리뷰 비교

| 관점 | Sonnet | Gemini | 최종 판단 |
|------|--------|--------|----------|
| 완성도 | 번역 매핑 로직 누락, 실패 청크 처리, 체크포인트 경로 생성 | 동일 + 문장 분리 로직, EPUB 해시 검증 | **Gemini 추가 항목은 [선택]으로 분류** |
| 리스크 | HTML 태그 손상, chunk_id 충돌 | HTML 태그 손상 강조, 토큰 수 불일치 추가 | **공통 이슈: HTML 태그 보존이 최대 리스크** |
| 성능 | 체크포인트 파일 크기 (낮음) | 체크포인트 저장 빈도 상세 분석 | **v2 이슈로 분류** |
| 구조 | 충분 | pipeline.py 분리, Chunk에 translated_text 추가 | **pipeline.py 분리는 유용하나 v2** |
| 보안 | 파일 경로 트래버설 경미 | 특이사항 없음 | **낮은 리스크, 권장 수준** |

---

## 최종 결론

**수정 필요** — 아래 3개 항목을 설계서(`02-design.md`)에 추가 명시 후 구현 진행:

1. `run_pipeline()`에서 번역 결과 → block_index 매핑 로직
2. `build_epub()`에서 누락된 block_index 원문 유지 로직
3. `checkpoint.py`의 디렉토리 자동 생성 처리

이 항목들은 코드 수준 변경이 아니라 **설계서에 처리 방법을 명문화**하는 것으로 해결 가능하며, 재설계는 불필요하다.
