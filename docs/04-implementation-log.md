# 구현 로그

## 생성/수정된 파일

- `src/__init__.py` — 패키지 초기화 (빈 파일)
- `requirements.txt` — 의존성 정의 (ebooklib, bs4, lxml, openai, tqdm)
- `src/checkpoint.py` — 체크포인트 저장/로드 (atomic write: tempfile + os.replace)
- `src/epub_parser.py` — EPUB 파싱, TextBlock/Chapter 데이터클래스, 블록 요소 추출
- `src/chunker.py` — TextBlock → Chunk 분할 (max_words 기준), 컨텍스트 추출
- `src/translator.py` — MLX-LM API 호출, 프롬프트 조립, exponential backoff 재시도
- `src/epub_builder.py` — 원본 EPUB + 번역 텍스트 → 새 EPUB 생성, fallback 처리
- `translate.py` — CLI 진입점 (argparse), 파이프라인 오케스트레이션, 번역→블록 매핑

## 설계서 대비 변경점

- **프롬프트 파라미터**: 설계서의 `temperature=0.1`, `top_p=0.3` 사용 (team-lead 지시의 `temperature=0.3`, `top_p=0.9`와 다름 — 설계서 우선)
- **프롬프트 텍스트**: 설계서의 상세 SYSTEM_PROMPT + USER_PROMPT_TEMPLATE 사용 (team-lead 지시의 간단 버전 대신 설계서 우선)
- **`_check_server()`**: httpx 사용 (openai 의존성에 이미 포함)

## 리뷰 반영 내역

- [필수] #1 번역 결과 → TextBlock 매핑 로직 → `_map_translation_to_blocks()` 구현 완료
- [필수] #2 실패 청크 build_epub 처리 → `build_epub()`에서 `translated_chapters.get()` fallback + WARNING 로그 구현 완료
- [필수] #3 체크포인트 디렉토리 자동 생성 → `save_progress()`에서 `Path.parent.mkdir(parents=True)` 구현 완료
- [권장] #4 `--resume` 시 `max_words` 변경 경고 → `run_pipeline()`에서 WARNING 출력 구현 완료
- [권장] #5 timeout 파라미터 → 미반영 (openai 클라이언트 기본값 사용, 필요 시 추가)
- [권장] #7 출력 파일 경로 안전성 → `run_pipeline()`에서 `mkdir + exists 경고` 구현 완료

## 알려진 이슈

- `translate_chunk()`에 명시적 timeout 미설정 (openai 기본 600초)
- HTML 태그 유효성 검증 미구현 (리뷰 #6, 권장 사항)
- 실제 EPUB End-to-End 테스트 미실행 (MLX-LM 서버 필요)

## 실행 확인

```
=== Test 1: Module imports ===
PASS: All modules imported successfully

=== Test 2: Checkpoint save/load ===
PASS: Checkpoint save/load works correctly

=== Test 3: Chunker logic ===
  4 blocks → 3 chunks (max_words=15)
PASS: Chunker splits correctly

=== Test 4: _extract_last_sentences ===
PASS: Sentence extraction works

=== Test 5: _map_translation_to_blocks ===
  Match / Mismatch / Single block cases all OK
PASS: Translation mapping works

ALL SMOKE TESTS PASSED
```
