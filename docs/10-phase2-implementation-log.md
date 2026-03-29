# Phase 2 구현 로그

**구현일:** 2026-03-30
**설계서:** 08-phase2-design.md
**리뷰:** 09-phase2-design-review.md

---

## 생성/수정된 파일

| 파일 | 상태 | 역할 |
|------|------|------|
| `server.py` | NEW | FastAPI 메인 앱 — 5개 API 엔드포인트 + 정적 파일 서빙 |
| `task_manager.py` | NEW | 번역 작업 생명주기 관리 — TaskInfo, TaskStatus, BufferLogHandler |
| `static/index.html` | NEW | 커스텀 UI — code.html 기반, id 바인딩 추가 |
| `static/app.js` | NEW | Vanilla JS 프론트엔드 — SSE, FormData, 프로그레스, 로그 |
| `translate.py` | MOD | cancel_event + log_handler 파라미터 추가 (기존 CLI 호환 유지) |
| `run.sh` | MOD | Gradio 실행 -> FastAPI(uvicorn) 실행으로 변경 |
| `requirements.txt` | MOD | gradio 제거, fastapi/uvicorn/python-multipart/httpx 추가 |

---

## 설계서 대비 변경점

### 1. translate.py 내부 구조 분리
설계서는 run_pipeline() 내부에 try/finally를 직접 감싸는 방식이었으나, 코드 가독성을 위해 `_run_pipeline_inner()`로 내부 로직을 분리하고 `run_pipeline()`은 log_handler 등록/해제만 담당하게 변경했다. 동작은 동일하다.

### 2. HTML 구조 일부 조정
- code.html의 nav 링크 중 "Library", "Translation Memory", "Settings"를 제거 (기능 없음, 지시사항에 따라)
- 모바일 하단 네비게이션도 제거 (SPA 미구현 상태에서 의미 없음)
- 엔드포인트/모델 입력 필드를 설계서 요구에 따라 추가
- API 키 필드는 Local 엔진 선택 시 숨김 처리

### 3. SVG viewBox 추가
code.html의 SVG에 viewBox가 없어 크기 조절이 부정확했다. `viewBox="0 0 128 128"` 추가.

### 4. stroke-dasharray 보정
설계서의 원형 프로그레스는 `2 * PI * 58 = 364.42`가 정확한 둘레인데, code.html은 364로 반올림되어 있었다. 364.42로 보정.

---

## 리뷰 반영 내역

### 필수 항목 (5/5 반영 완료)

| # | 항목 | 상태 | 구현 위치 |
|---|------|------|----------|
| 1 | Path Traversal 방지 | 반영 | server.py: `Path(file.filename).name` |
| 2 | 파일 크기 50MB 제한 | 반영 | server.py: `len(content) > MAX_FILE_SIZE` -> 413 |
| 3 | SSE에서 asyncio.to_thread 사용 | 반영 | server.py: `await asyncio.to_thread(load_progress, ...)` |
| 4 | 동시 번역 Semaphore(2) 제한 | 반영 | server.py: `_translation_semaphore = asyncio.Semaphore(MAX_CONCURRENT)` |
| 5 | startup cleanup 백그라운드 태스크 | 반영 | server.py: `_cleanup_loop()` — 1시간 주기, 24시간 이상 작업 정리 |

### 권장 항목 (4/4 반영 완료)

| # | 항목 | 상태 | 구현 위치 |
|---|------|------|----------|
| 6 | task_id 12자로 연장 | 반영 | server.py: `uuid4()[:12]` |
| 7 | output_path에 task_id 포함 | 반영 | server.py: `f"{task_id}_{stem}_kr.epub"` |
| 8 | CORS origins 환경변수 분리 | 반영 | server.py: `os.getenv("CORS_ORIGINS", ...)` |
| 9 | log_buffer 단일 스냅샷 패턴 | 반영 | server.py: `snapshot = list(task.log_buffer)` |

### 선택 항목

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 10 | provider Enum 검증 | 미반영 | Form 문자열로 유지, LLMClient 내부에서 검증함 |
| 11 | SSE 재연결 5회 제한 | 반영 | app.js: `reconnectCount` 카운터 구현 |

---

## 알려진 이슈

1. **app.py (Gradio) 미삭제:** 설계서에 "Phase 2 완료 후 제거"로 명시. 현재는 공존 상태.
2. **모바일 하단 네비 제거:** SPA가 아니므로 네비게이션이 의미 없어 제거했으나, 향후 멀티페이지 구현 시 복원 필요.
3. **SSE Last-Event-Id 미구현:** 설계서 결정대로 미구현. 재연결 시 체크포인트에서 상태 재동기화.
4. **logging 루트 핸들러:** 웹 서버 실행 시 로그 포맷 설정이 별도로 필요할 수 있음 (현재 uvicorn 기본 포맷 사용).

---

## 실행 확인

### 1. import 검증
```
$ python3 -c "import task_manager"        -> OK
$ python3 -c "import server"              -> OK
$ python3 -c "import translate"           -> OK (cancel_event, log_handler 파라미터 확인)
```

### 2. uvicorn 기동 확인
```
$ uvicorn server:app --host 127.0.0.1 --port 8001
INFO: Application startup complete.
INFO: Uvicorn running on http://127.0.0.1:8001
```

### 3. API 엔드포인트 검증
```
GET  /                    -> 200 (index.html 반환)
GET  /api/checkpoints     -> 200 {"checkpoints": [...]}
```

### 4. CLI 호환성
```
run_pipeline() 시그니처: cancel_event=None, log_handler=None
main() 시그니처: 변경 없음
```
