# Phase 2 설계 리뷰 — EPUB Translator Studio (FastAPI + Custom HTML)

**작성일:** 2026-03-29
**리뷰어:** Sonnet 4.6 + Gemini 2.5 Flash (교차 리뷰)
**대상:** 08-phase2-design.md

---

## 평가 요약

**수정 필요**

핵심 아키텍처 결정(asyncio.to_thread + threading.Event)은 올바르다. 설계 완성도도 높다.
그러나 구현 전에 반드시 해결해야 할 [필수] 항목 5개가 있으며, 이들을 수정하면 통과 판정이다.
재설계는 불필요하다 — 방향은 맞고, 세부 구현에서 빠진 안전장치들이다.

---

## 강점

1. **asyncio.to_thread 선택 근거가 명확함** — 기존 동기 run_pipeline()을 async로 전면 개조하지 않고, 스레드 분리로 최소 변경을 달성한 점은 pragmatic하다.

2. **threading.Event 취소 메커니즘이 정확함** — asyncio.Event는 이벤트 루프 바운드이므로 worker thread에서 is_set() 호출 시 문제가 생긴다. 이 차이를 설계서에서 명시적으로 설명하고 있어 구현 오류 가능성이 낮다.

3. **translate.py 변경 최소화 원칙이 실용적** — cancel_event / log_handler 파라미터를 `None` 기본값으로 추가해 CLI 호환성을 유지한 설계는 올바르다. 실제 translate.py를 확인한 결과 현재 시그니처와도 충돌이 없다.

4. **SSE 선택이 적절함** — 번역 진행률은 단방향 데이터이므로 WebSocket 대비 SSE가 단순하고 안정적이다. 재연결도 EventSource가 자동 처리한다.

5. **체크포인트 atomic write가 이미 구현됨** — src/checkpoint.py가 tempfile + os.replace()로 crash-safe 저장을 구현하고 있다. SSE 재연결 후 자연스러운 상태 동기화가 가능한 토대가 갖춰져 있다.

6. **에러 분류표가 구체적** — 에러 시나리오별 발생 위치, 감지 방법, 복구 전략이 표 형태로 명시되어 있어 구현 누락 가능성이 낮다.

---

## 개선 필요

### [필수] 1. 파일 경로 안전성 — Path Traversal 위험

**위치:** server.py, POST /api/translate

**문제:** `file.filename`을 검증 없이 경로에 직접 사용한다.
```python
# 현재 설계
input_path = os.path.join(UPLOAD_DIR, f"{task_id}_{file.filename}")
# file.filename = "../../etc/cron.d/evil.epub" 이면 uploads/ 밖에 저장됨
```

**수정:**
```python
from pathlib import Path

safe_name = Path(file.filename).name  # 경로 성분 제거, 파일명만 추출
input_path = os.path.join(UPLOAD_DIR, f"{task_id}_{safe_name}")
```

`Path(file.filename).name`은 `/` `..` 등 경로 성분을 모두 제거한다.
output_path, checkpoint_path도 동일하게 safe_name 기준으로 구성해야 한다.

---

### [필수] 2. 파일 크기 제한이 누락됨

**위치:** server.py, POST /api/translate

**문제:** 에러 처리 표에는 "50MB 초과 파일 → 413"이 명시되어 있으나, 실제 구현 코드 스니펫에 이 검증이 없다.
현재 코드는 `content = await file.read()`로 파일 전체를 메모리에 읽은 후 저장한다.
500MB EPUB이 들어오면 서버가 OOM으로 크래시된다.

**수정 — 두 가지 방법 중 하나:**

방법 A (현재 방식 유지 + 크기 체크):
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

content = await file.read()
if len(content) > MAX_FILE_SIZE:
    raise HTTPException(413, f"파일이 50MB를 초과합니다 ({len(content) // (1024*1024)}MB).")
with open(input_path, "wb") as f:
    f.write(content)
```

방법 B (스트리밍 저장, 메모리 효율적):
```python
import aiofiles

size = 0
async with aiofiles.open(input_path, "wb") as f:
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_FILE_SIZE:
            await f.close()
            os.unlink(input_path)
            raise HTTPException(413, "파일이 50MB를 초과합니다.")
        await f.write(chunk)
```

방법 B가 메모리 효율적이나, 의존성(aiofiles) 추가가 필요하다.
Phase 2 현실적인 파일 크기(수 MB)라면 방법 A로도 충분하다.

---

### [필수] 3. SSE event_generator에서 동기 I/O가 이벤트 루프를 블로킹함

**위치:** server.py, GET /api/progress/{task_id}

**문제:**
```python
async def event_generator():
    while True:
        ckpt = load_progress(task.checkpoint_path)  # 동기 파일 I/O
        ...
        await asyncio.sleep(1)
```

`load_progress()`는 동기 함수다. JSON 파일을 열고, 파싱하고, 반환한다.
이 호출이 이벤트 루프 스레드에서 직접 실행되므로, 파일 I/O가 느려지거나 체크포인트가 크면 전체 SSE 스트리밍이 지연된다.

**수정:**
```python
async def event_generator():
    while True:
        ckpt = await asyncio.to_thread(load_progress, task.checkpoint_path)
        ...
        await asyncio.sleep(1)
```

`asyncio.to_thread`로 감싸면 worker thread에서 실행되어 이벤트 루프가 자유롭다.

---

### [필수] 4. 동시 번역 요청 수 제한 없음

**위치:** server.py, 전역

**문제:** 현재 설계에는 동시에 실행될 수 있는 번역 작업 수에 상한이 없다.
MLX-LM 로컬 서버는 메모리(VRAM/RAM) 한계가 있으므로, 3명이 동시에 번역을 시작하면
LLM 서버가 OOM으로 크래시되거나 응답 시간이 급격히 늘어난다.
클라우드 API 프로바이더는 rate limit 초과 에러를 낸다.

**수정:**
```python
# server.py 상단 (앱 생성 후)
MAX_CONCURRENT = 2
_translation_semaphore: asyncio.Semaphore | None = None

@app.on_event("startup")
async def startup():
    global _translation_semaphore
    _translation_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# _run_in_background 수정
async def _run_in_background():
    async with _translation_semaphore:
        task.status = TaskStatus.RUNNING
        log_handler = BufferLogHandler(task.log_buffer)
        try:
            await asyncio.to_thread(run_pipeline, ...)
            ...
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
```

세마포어 획득 대기 중인 작업은 status=PENDING으로 유지되며, SSE progress 이벤트에 "pending" 상태가 표시된다. 사용자에게 "대기 중" 피드백을 주는 것도 병행해야 한다.

---

### [필수] 5. 완료된 작업이 메모리에 영구 잔류함 (Task 누수)

**위치:** task_manager.py, _tasks dict

**문제:** `_tasks`에서 완료/취소/실패 작업이 제거되지 않는다.
각 TaskInfo는 deque(maxlen=500) 로그 버퍼, threading.Event, 파일 경로 등을 포함한다.
서버가 장시간 운영되거나 많은 번역 요청이 들어오면 메모리 사용량이 단조 증가한다.
업로드된 EPUB 파일(uploads/)도 디스크에 영구적으로 잔류한다.

**수정 — 백그라운드 정리 태스크 추가:**
```python
# server.py

@app.on_event("startup")
async def startup():
    asyncio.create_task(_cleanup_loop())

async def _cleanup_loop():
    """완료된 작업과 임시 파일을 24시간 후 정리."""
    while True:
        await asyncio.sleep(3600)  # 1시간마다 실행
        now = datetime.now()
        terminal_statuses = {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}
        to_remove = []

        for task_id, task in list(_tasks.items()):
            if task.status in terminal_statuses:
                age = (now - task.created_at).total_seconds()
                if age > 86400:  # 24시간
                    to_remove.append(task_id)

        for task_id in to_remove:
            task = _tasks.pop(task_id, None)
            if task and os.path.exists(task.input_path):
                try:
                    os.unlink(task.input_path)
                    logger.info("임시 업로드 파일 삭제: %s", task.input_path)
                except OSError as e:
                    logger.warning("파일 삭제 실패: %s — %s", task.input_path, e)
```

---

### [권장] 6. task_id가 8자로 너무 짧음

**위치:** server.py

**문제:** `str(uuid.uuid4())[:8]`는 16진 문자 8개 = 약 43억 가지 조합이다.
단일 인스턴스 개인 사용이라면 충돌 확률은 무시할 수 있지만,
`_tasks` 딕셔너리의 key가 중복되면 기존 작업이 silently 덮어씌워진다.

**수정 옵션 A (최소 변경):**
```python
task_id = str(uuid.uuid4())[:12]  # 8 → 12자로 연장
```

**수정 옵션 B (충돌 방지 보장):**
```python
task_id = str(uuid.uuid4())  # 전체 UUID 사용 (36자)
```

URL에 task_id가 포함되므로 36자가 길어 보일 수 있으나, 기능적으로는 더 안전하다.

---

### [권장] 7. output_path가 task_id 없이 생성되어 동시 번역 시 충돌

**위치:** server.py, POST /api/translate

**문제:**
```python
output_path = os.path.join(OUTPUT_DIR, f"{stem}_kr.epub")
# 같은 책 파일을 두 번 업로드하면 같은 output_path 생성
# 두 번째 번역이 첫 번째 결과를 덮어씌움
```

**수정:**
```python
output_path = os.path.join(OUTPUT_DIR, f"{task_id}_{stem}_kr.epub")
```

task_id가 포함되면 동일 파일 이름도 충돌 없이 독립적으로 저장된다.

---

### [권장] 8. CORS allow_origins=["*"] — 프로덕션 배포 시 위험

**위치:** server.py

**문제:** 현재 설계에는 CORS 설정이 `allow_origins=["*"]`로 하드코딩되어 있다.
개발 단계에서는 편리하지만, 이 상태로 외부에 노출되면 모든 도메인에서 API 접근이 가능하다.
파일 업로드 + 번역 실행 API이므로 악의적인 외부 사이트에서 악용될 수 있다.

**수정 — 환경변수로 분리:**
```python
import os
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    ...
)
```

로컬 전용 사용이라면 `["http://localhost:8000", "http://127.0.0.1:8000"]`으로도 충분하다.

---

### [권장] 9. log_buffer 접근 시 스레드 안전성 미흡

**위치:** task_manager.py

**문제:**
- Worker thread: `BufferLogHandler.emit()` → `log_buffer.append()`
- Main thread (이벤트 루프): `event_generator` → `list(task.log_buffer)` + `len(task.log_buffer)`

`collections.deque`의 개별 연산(append, len)은 CPython GIL 덕분에 원자적이나,
`list(task.log_buffer)[log_cursor:current_len]` 패턴처럼 len()과 list() 사이에 append()가 끼어들면
슬라이스 인덱스가 범위를 초과할 수 있다.

**수정:**
```python
# event_generator 내 로그 읽기 부분
snapshot = list(task.log_buffer)  # 단일 복사 (더 안전)
if len(snapshot) > log_cursor:
    new_logs = snapshot[log_cursor:]
    for entry in new_logs:
        yield f"event: log\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n"
    log_cursor = len(snapshot)
```

`list(task.log_buffer)`를 한 번만 호출해 스냅샷을 만들면, 그 이후 append가 발생해도 슬라이스가 안전하다.

---

### [선택] 10. provider 입력값 enum 검증 없음

**위치:** server.py

**문제:** `provider: str = Form("local")`은 임의 문자열을 허용한다.
`LLMClient` 내부에서 `ValueError`가 발생하긴 하지만, FastAPI 레이어에서 미리 거르는 것이 더 안전하고 에러 메시지도 명확하다.

**수정:**
```python
from enum import Enum

class ProviderEnum(str, Enum):
    local = "local"
    openai = "openai"
    claude = "claude"

@app.post("/api/translate")
async def start_translation(
    provider: ProviderEnum = Form(ProviderEnum.local),
    ...
):
```

---

### [선택] 11. 재연결 5회 실패 카운트 구현 누락

**위치:** static/app.js

**문제:** 설계서에 "5회 재연결 실패 시 수동 새로고침 안내"가 명시되어 있으나,
실제 app.js 코드 스니펫에는 `es.onerror = () => { // 별도 처리 불필요 }`로 비워져 있다.
설계서와 코드 사이에 불일치가 있다.

**수정:** 재연결 카운터를 구현하거나, 설계서의 "5회 실패 시 안내" 요구사항을 제거해 일관성을 맞춰야 한다.
```javascript
// app.js 수정안
let reconnectCount = 0;
es.onerror = () => {
    reconnectCount++;
    if (reconnectCount > 5) {
        es.close();
        ui.showError('서버 연결이 불안정합니다. 페이지를 새로고침하세요.');
        ui.setStatus('failed');
    }
};
```

---

## 리스크 평가

| 리스크 | 심각도 | 현재 상태 | 처리 여부 |
|--------|--------|----------|----------|
| Path Traversal (파일 저장) | 높음 | 미처리 | [필수] #1에서 수정 |
| 파일 크기 제한 미적용 | 높음 | 설계서에만 언급 | [필수] #2에서 수정 |
| 동시 번역 제한 없음 | 높음 | 미처리 | [필수] #4에서 수정 |
| Task 누수 / 파일 누적 | 중간 | 미처리 | [필수] #5에서 수정 |
| SSE에서 동기 I/O 블로킹 | 중간 | 미처리 | [필수] #3에서 수정 |
| output_path 충돌 | 중간 | 미처리 | [권장] #7에서 수정 |
| CORS 개방 | 중간 | 개발용이라 명시됨 | [권장] #8에서 수정 |
| log_buffer 스레드 안전 | 낮음 | 미처리 | [권장] #9에서 수정 |
| task_id 충돌 | 낮음 | 미처리 | [권장] #6에서 수정 |
| asyncio.to_thread 오버헤드 | 낮음 | 설계서에 인지됨 | 벤치마크로 확인 |

---

## 수정 제안 요약

**구현 시작 전 반드시 적용 (필수 5개):**

1. `Path(file.filename).name`으로 안전한 파일명 추출
2. `file.read()` 전 파일 크기 검증 추가 (50MB 상한)
3. `load_progress()` 호출을 `asyncio.to_thread`로 래핑
4. `asyncio.Semaphore(2)`로 동시 번역 수 제한
5. `@app.on_event("startup")`에 cleanup 백그라운드 태스크 등록

**구현 중 적용 (권장 4개):**

6. task_id를 12자 이상으로 연장
7. output_path에 task_id 포함
8. CORS origins를 환경변수로 분리
9. log_buffer 읽기를 단일 스냅샷 패턴으로 변경

---

## Gemini 리뷰 의견

Gemini 2.5 Flash에 `docs/08-phase2-design.md` 전문을 전달하여 교차 리뷰를 수행했다.

**주요 지적 사항 (Gemini):**

1. **Path Traversal + 파일 크기:** Sonnet과 동일하게 지적. `Path().name` 추출 + aiofiles 스트리밍 저장 권장.
2. **CORS:** `allow_origins=["*"]` 프로덕션 위험 강조. 환경변수화 권장.
3. **input 검증:** `provider` Enum화, `max_words` ge/le 범위 제한을 FastAPI Form 레이어에서 처리할 것.
4. **스레드 안전성:** `_tasks` 딕셔너리 접근에 `threading.Lock` 사용 권장. CPython GIL로 단순 get/set은 안전하나 복합 연산은 취약.
5. **log_cursor 클라이언트별 관리:** 재연결 시 로그 중복 전송 문제. `TaskInfo.log_cursor` 필드가 설계에 있으나 event_generator에서 미사용. client_id 기반으로 활용하거나 명시적으로 트레이드오프를 문서화할 것.
6. **동시 번역 제한:** `asyncio.Semaphore` 사용 강조.
7. **Task 정리:** 완료/실패 작업 주기적 정리 필요. cleanup_old_tasks() 구현 권장.
8. **SSE load_progress 블로킹:** `asyncio.to_thread`로 래핑 권장 (Sonnet과 동일).
9. **설정 중앙화:** `pydantic-settings` 기반 Settings 클래스로 하드코딩된 경로/설정 분리 권장.
10. **헬스체크 엔드포인트 추가:** `/health` 엔드포인트 추가 권장.

---

## 모델 간 리뷰 비교

| 관점 | Sonnet | Gemini | 최종 판단 |
|------|--------|--------|----------|
| Path Traversal | 필수 수정 | 필수 수정 | 동일 — [필수] #1 |
| 파일 크기 제한 | 필수 수정 | 필수 수정 | 동일 — [필수] #2 |
| SSE I/O 블로킹 | 필수 수정 | 필수 수정 | 동일 — [필수] #3 |
| 동시 번역 제한 | 필수 수정 | 필수 수정 | 동일 — [필수] #4 |
| Task 누수 | 필수 수정 | 필수 수정 | 동일 — [필수] #5 |
| CORS | 권장 수정 | 권장 수정 | 동일 — [권장] #8 |
| log_buffer 안전성 | 권장 수정 | threading.Lock 추가 권장 | Gemini가 더 강경 — CPython GIL에 의존하지 말고 명시적 Lock 사용 고려 |
| _tasks 딕셔너리 Lock | 언급 없음 | 필수 수정 | Gemini 추가 발견 — 단일 인스턴스+소수 요청이면 실질적 위험 낮음, 필요 시 추가 |
| pydantic-settings | 언급 없음 | 권장 | Phase 3으로 미룰 수 있음 |
| 헬스체크 엔드포인트 | 언급 없음 | 선택 | 배포 환경에 따라 결정 |
| 취소의 즉각성 | 언급 없음 | 청크 번역 중 취소 지연 | 현재 구현 한계 — 문서에 명시하고 허용 |
| output_path 충돌 | 권장 수정 | 언급 없음 | Sonnet 추가 발견 — [권장] #7 |
| task_id 길이 | 권장 수정 | 언급 없음 | 낮은 위험, [권장] #6 |
