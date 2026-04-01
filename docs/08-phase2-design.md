# Phase 2 기술 설계서 — EPUB Translator Studio (FastAPI + Custom HTML)

**작성일:** 2026-03-29
**기반:** 07-phase2-research.md (자료조사), 02-design.md (Phase 1 설계), code.html (디자인)

---

## 설계 개요

Gradio 기반 Phase 1 UI를 제거하고, FastAPI 백엔드 + Vanilla JS 프론트엔드로 전환한다.
핵심 번역 파이프라인(`translate.py`, `src/`)은 최소한만 수정하며, 새로운 서버 레이어(`server.py`, `task_manager.py`)가 기존 `run_pipeline()`을 비동기로 래핑한다. 실시간 진행률은 SSE로 푸시하고, 번역 중단은 `threading.Event`로 구현한다.

**변경 범위 요약:**
- **신규 파일 4개:** `server.py`, `task_manager.py`, `static/index.html`, `static/app.js`
- **수정 파일 2개:** `translate.py` (cancel_event + log_handler 파라미터 추가), `run.sh` (uvicorn 실행)
- **변경 없음:** `src/` 전체 (epub_parser, chunker, translator, checkpoint, epub_builder, providers)
- **삭제:** `app.py` (Gradio UI) — Phase 2 완료 후 제거

---

## 아키텍처

### 컴포넌트 다이어그램

```
┌─────────────────────────────────────────────────────────┐
│              Browser (static/index.html + app.js)        │
│  ┌──────────┐ ┌──────────────┐ ┌────────┐ ┌──────────┐ │
│  │ 파일업로드 │ │SSE EventSource│ │취소 버튼│ │다운로드   │ │
│  └─────┬────┘ └──────┬───────┘ └───┬────┘ └────┬─────┘ │
└────────┼─────────────┼─────────────┼───────────┼───────┘
         │             │             │           │
    POST /api/    GET /api/     POST /api/   GET /api/
    translate     progress/     cancel/      download/
         │        {task_id}     {task_id}    {task_id}
         │             │             │           │
┌────────▼─────────────▼─────────────▼───────────▼───────┐
│                    server.py (FastAPI)                   │
│  ┌─────────────────────────────────────────────────┐   │
│  │  StaticFiles("/", "static")                      │   │
│  │  CORS middleware (개발용)                          │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
│              ┌──────────▼──────────┐                   │
│              │   task_manager.py    │                   │
│              │  ┌────────────────┐  │                   │
│              │  │ tasks: dict     │  │                   │
│              │  │ task_id→TaskInfo│  │                   │
│              │  └────────────────┘  │                   │
│              └──────────┬──────────┘                   │
└─────────────────────────┼──────────────────────────────┘
                          │
              asyncio.to_thread(run_pipeline)
                          │
              ┌───────────▼───────────┐
              │    translate.py        │
              │    run_pipeline()      │
              │  + cancel_event 체크   │
              │  + log_handler 캡처    │
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │       src/ 모듈        │
              │  epub_parser.py        │
              │  chunker.py            │
              │  translator.py         │
              │  checkpoint.py         │
              │  epub_builder.py       │
              │  providers.py          │
              └───────────┬───────────┘
                          │
              ┌───────────▼───────────┐
              │  LLM Server           │
              │  (MLX-LM / OpenAI /   │
              │   Claude API)          │
              └───────────────────────┘
```

### 스레딩 모델

```
Main Thread (uvicorn event loop)
  │
  ├── GET /api/progress/{task_id}  →  async generator (SSE)
  ├── POST /api/translate          →  asyncio.to_thread(run_pipeline) 시작
  ├── POST /api/cancel/{task_id}   →  cancel_event.set()
  └── GET /api/download/{task_id}  →  FileResponse

Worker Thread (asyncio.to_thread 내부)
  │
  └── run_pipeline()  ← 동기 함수, 기존 로직 유지
      ├── 매 청크 전 cancel_event.is_set() 체크
      └── 매 로그 발생 시 log_handler로 버퍼에 push
```

**핵심 결정: `asyncio.to_thread` vs `asyncio.create_task`**

리서치에서는 `asyncio.create_task` + `run_pipeline_async`를 제안했으나, **`asyncio.to_thread`를 선택**한다.

근거:
1. `run_pipeline()`은 완전 동기 함수 — 내부에서 `translate_chunk()` → `client.complete()` → HTTP 요청이 모두 동기
2. `asyncio.create_task`를 쓰려면 루프 내부를 모두 async로 바꿔야 함 → **변경 범위 과대**
3. `asyncio.to_thread`는 별도 스레드에서 동기 함수를 실행하며, `threading.Event`로 취소 신호 전달 가능
4. 이벤트 루프 블로킹 없음 — SSE 스트리밍 정상 동작

**취소 메커니즘: `threading.Event` (asyncio.Event 아님)**

근거:
- `run_pipeline()`은 worker thread에서 실행됨
- `asyncio.Event`는 이벤트 루프 바운드 → 다른 스레드에서 `.is_set()` 호출 시 문제
- `threading.Event`는 스레드 안전, 어디서든 `.set()` / `.is_set()` 가능

---

## 파일 구조

```
kindle-translator/
├── server.py              # [NEW] FastAPI 메인 앱 — 라우터 + 정적파일 서빙
├── task_manager.py        # [NEW] 번역 작업 생명주기 관리
├── static/
│   ├── index.html         # [NEW] 커스텀 UI (code.html 기반, 동적 바인딩 추가)
│   └── app.js             # [NEW] Vanilla JS — SSE, FormData, DOM 업데이트
├── translate.py           # [MOD] run_pipeline에 cancel_event, log_handler 추가
├── src/
│   ├── __init__.py        # 변경 없음
│   ├── epub_parser.py     # 변경 없음
│   ├── chunker.py         # 변경 없음
│   ├── translator.py      # 변경 없음
│   ├── epub_builder.py    # 변경 없음
│   ├── checkpoint.py      # 변경 없음
│   └── providers.py       # 변경 없음
├── app.py                 # [DEL] Phase 2 완료 후 제거 (Gradio)
├── uploads/               # [NEW] 업로드된 EPUB 임시 저장
├── outputs/               # [NEW] 번역 결과 EPUB 저장
├── checkpoints/           # 기존 유지
├── run.sh                 # [MOD] uvicorn server:app 실행
├── requirements.txt       # [MOD] gradio 제거, fastapi+uvicorn 추가
└── docs/
    └── 08-phase2-design.md  # 이 파일
```

### 파일별 책임

| 파일 | 책임 | 라인 수 (추정) |
|------|------|---------------|
| `server.py` | FastAPI 앱 생성, 라우터 정의, StaticFiles 마운트, 에러 핸들러 | ~150 |
| `task_manager.py` | TaskInfo 데이터 클래스, 작업 생성/조회/취소, 로그 버퍼 관리 | ~120 |
| `static/index.html` | code.html 기반, id 속성 추가, 동적 바인딩 포인트 | ~320 |
| `static/app.js` | SSE 구독, FormData 업로드, 프로그레스 업데이트, 로그 렌더링 | ~300 |
| `translate.py` (수정분) | cancel_event 체크 + log_handler 파라미터 2개 추가 | +15줄 |

---

## 핵심 인터페이스

### 1. `task_manager.py` — 데이터 구조

```python
import threading
import logging
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from collections import deque


class TaskStatus(str, Enum):
    PENDING = "pending"         # 생성됨, 아직 시작 안 함
    RUNNING = "running"         # 번역 진행 중
    COMPLETED = "completed"     # 정상 완료
    CANCELLED = "cancelled"     # 사용자 취소
    FAILED = "failed"           # 에러로 실패


@dataclass
class TaskInfo:
    task_id: str
    filename: str                           # 원본 EPUB 파일명
    input_path: str                         # uploads/ 내 경로
    output_path: str                        # outputs/ 내 경로
    checkpoint_path: str                    # checkpoints/ 내 경로
    status: TaskStatus = TaskStatus.PENDING
    cancel_event: threading.Event = field(default_factory=threading.Event)
    log_buffer: deque = field(default_factory=lambda: deque(maxlen=500))
    log_cursor: dict = field(default_factory=dict)  # client_id → last_read_index
    created_at: datetime = field(default_factory=datetime.now)
    error_message: str = ""

    # 진행률 (체크포인트에서 읽음)
    total_chunks: int = 0
    completed_chunks: int = 0
    failed_chunks: int = 0
    book_title: str = ""


class BufferLogHandler(logging.Handler):
    """로그 레코드를 TaskInfo.log_buffer에 push하는 핸들러."""

    def __init__(self, log_buffer: deque):
        super().__init__()
        self.log_buffer = log_buffer

    def emit(self, record: logging.LogRecord):
        entry = {
            "time": self.format_time(record),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        self.log_buffer.append(entry)

    @staticmethod
    def format_time(record: logging.LogRecord) -> str:
        return datetime.fromtimestamp(record.created).strftime("%H:%M:%S")


# 전역 작업 저장소
_tasks: dict[str, TaskInfo] = {}


def create_task(task_id: str, filename: str, input_path: str,
                output_path: str, checkpoint_path: str) -> TaskInfo:
    """새 작업을 생성하고 전역 저장소에 등록한다."""
    task = TaskInfo(
        task_id=task_id,
        filename=filename,
        input_path=input_path,
        output_path=output_path,
        checkpoint_path=checkpoint_path,
    )
    _tasks[task_id] = task
    return task


def get_task(task_id: str) -> TaskInfo | None:
    """task_id로 작업을 조회한다."""
    return _tasks.get(task_id)


def get_all_tasks() -> list[TaskInfo]:
    """모든 작업 목록을 반환한다 (최신순)."""
    return sorted(_tasks.values(), key=lambda t: t.created_at, reverse=True)


def cancel_task(task_id: str) -> bool:
    """작업 취소 신호를 보낸다. 존재하면 True."""
    task = _tasks.get(task_id)
    if task and task.status == TaskStatus.RUNNING:
        task.cancel_event.set()
        return True
    return False
```

### 2. `server.py` — FastAPI 엔드포인트

```python
import asyncio
import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from task_manager import (
    TaskInfo, TaskStatus, BufferLogHandler,
    create_task, get_task, get_all_tasks, cancel_task,
)
from src.providers import LLMClient, DEFAULT_MODELS
from src.checkpoint import load_progress
from translate import run_pipeline

app = FastAPI(title="EPUB Translator Studio")

# CORS (개발용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
CHECKPOINT_DIR = "checkpoints"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CHECKPOINT_DIR, exist_ok=True)
```

#### 2-1. `POST /api/translate` — 번역 시작

```python
@app.post("/api/translate")
async def start_translation(
    file: UploadFile = File(...),
    provider: str = Form("local"),
    model: str = Form(""),
    api_key: str = Form(""),
    endpoint: str = Form(""),
    max_words: int = Form(800),
    resume: bool = Form(False),
):
    """
    EPUB 파일을 업로드하고 번역 작업을 시작한다.

    Returns:
        {"task_id": "uuid", "status": "running", "filename": "book.epub"}
    """
    # 1. 파일 검증
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(400, "EPUB 파일만 업로드 가능합니다.")

    # 2. 파일 저장
    task_id = str(uuid.uuid4())[:8]
    stem = Path(file.filename).stem
    input_path = os.path.join(UPLOAD_DIR, f"{task_id}_{file.filename}")
    output_path = os.path.join(OUTPUT_DIR, f"{stem}_kr.epub")
    checkpoint_path = os.path.join(CHECKPOINT_DIR, f"{stem}_progress.json")

    content = await file.read()
    with open(input_path, "wb") as f:
        f.write(content)

    # 3. TaskInfo 생성
    task = create_task(task_id, file.filename, input_path, output_path, checkpoint_path)

    # 4. 모델/클라이언트 준비
    actual_model = model.strip() or DEFAULT_MODELS[provider]
    ep = endpoint.strip() or None
    key = api_key.strip() or None

    try:
        client = LLMClient(provider=provider, api_key=key, endpoint=ep)
    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error_message = f"클라이언트 초기화 실패: {e}"
        raise HTTPException(400, task.error_message)

    # 5. 로컬 서버 연결 확인
    if provider == "local" and not client.check_connection():
        task.status = TaskStatus.FAILED
        task.error_message = "MLX-LM 서버에 연결할 수 없습니다."
        raise HTTPException(503, task.error_message)

    # 6. 체크포인트 존재 시 자동 resume
    if os.path.exists(checkpoint_path) and not resume:
        ckpt = load_progress(checkpoint_path)
        if ckpt:
            done = ckpt.get("completed_chunks", 0)
            total = ckpt.get("total_chunks", 0)
            if 0 < done < total:
                resume = True

    # 7. 백그라운드 번역 시작
    task.status = TaskStatus.RUNNING

    async def _run_in_background():
        log_handler = BufferLogHandler(task.log_buffer)
        try:
            await asyncio.to_thread(
                run_pipeline,
                input_path=input_path,
                output_path=output_path,
                model=actual_model,
                checkpoint_path=checkpoint_path,
                resume=resume,
                max_words=max_words,
                client=client,
                cancel_event=task.cancel_event,      # NEW
                log_handler=log_handler,              # NEW
            )
            if task.cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
            else:
                task.status = TaskStatus.COMPLETED
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)

    asyncio.create_task(_run_in_background())

    return {
        "task_id": task_id,
        "status": "running",
        "filename": file.filename,
    }
```

#### 2-2. `GET /api/progress/{task_id}` — SSE 스트리밍

```python
@app.get("/api/progress/{task_id}")
async def stream_progress(task_id: str):
    """
    SSE 스트리밍으로 진행률과 로그를 실시간 전송한다.

    이벤트 종류:
    - event: progress  → 진행률 데이터
    - event: log       → 로그 메시지
    - event: done      → 작업 완료 신호
    - event: error     → 에러 발생
    """
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")

    async def event_generator():
        log_cursor = 0

        while True:
            # 체크포인트에서 진행률 읽기
            ckpt = load_progress(task.checkpoint_path)
            if ckpt:
                task.total_chunks = ckpt.get("total_chunks", 0)
                task.completed_chunks = ckpt.get("completed_chunks", 0)
                task.failed_chunks = ckpt.get("failed_chunks", 0)
                task.book_title = Path(ckpt.get("source", "")).stem

            progress_data = {
                "task_id": task_id,
                "status": task.status.value,
                "completed": task.completed_chunks,
                "total": task.total_chunks,
                "failed": task.failed_chunks,
                "filename": task.filename,
                "book_title": task.book_title,
            }
            yield f"event: progress\ndata: {json.dumps(progress_data, ensure_ascii=False)}\n\n"

            # 새 로그 전송
            current_len = len(task.log_buffer)
            if current_len > log_cursor:
                new_logs = list(task.log_buffer)[log_cursor:current_len]
                for log_entry in new_logs:
                    yield f"event: log\ndata: {json.dumps(log_entry, ensure_ascii=False)}\n\n"
                log_cursor = current_len

            # 종료 조건 확인
            if task.status == TaskStatus.COMPLETED:
                yield f"event: done\ndata: {json.dumps({'output': task.output_path})}\n\n"
                break
            elif task.status == TaskStatus.CANCELLED:
                yield f"event: done\ndata: {json.dumps({'status': 'cancelled'})}\n\n"
                break
            elif task.status == TaskStatus.FAILED:
                yield f"event: error\ndata: {json.dumps({'error': task.error_message})}\n\n"
                break

            await asyncio.sleep(1)  # 1초 주기

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

#### 2-3. `POST /api/cancel/{task_id}` — 번역 취소

```python
@app.post("/api/cancel/{task_id}")
async def cancel_translation(task_id: str):
    """
    진행 중인 번역을 취소한다.
    cancel_event.set()으로 run_pipeline 루프에 취소 신호를 보낸다.
    """
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")

    if task.status != TaskStatus.RUNNING:
        raise HTTPException(400, f"취소할 수 없는 상태: {task.status.value}")

    cancel_task(task_id)

    return {
        "task_id": task_id,
        "status": "cancelling",
        "message": "취소 신호를 보냈습니다. 현재 청크 완료 후 중단됩니다.",
    }
```

#### 2-4. `GET /api/download/{task_id}` — 결과 다운로드

```python
@app.get("/api/download/{task_id}")
async def download_result(task_id: str):
    """번역 완료된 EPUB 파일을 다운로드한다."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(400, "번역이 아직 완료되지 않았습니다.")

    if not os.path.exists(task.output_path):
        raise HTTPException(404, "출력 파일을 찾을 수 없습니다.")

    return FileResponse(
        path=task.output_path,
        filename=f"{Path(task.filename).stem}_kr.epub",
        media_type="application/epub+zip",
    )
```

#### 2-5. `GET /api/checkpoints` — 체크포인트 목록

```python
@app.get("/api/checkpoints")
async def list_checkpoints():
    """저장된 체크포인트 목록을 반환한다."""
    import glob as glob_mod

    files = glob_mod.glob(os.path.join(CHECKPOINT_DIR, "*_progress.json"))
    result = []

    for f in sorted(files, key=os.path.getmtime, reverse=True):
        try:
            ckpt = load_progress(f)
            if not ckpt:
                continue
            result.append({
                "filename": Path(ckpt.get("source", "")).name,
                "total": ckpt.get("total_chunks", 0),
                "completed": ckpt.get("completed_chunks", 0),
                "failed": ckpt.get("failed_chunks", 0),
                "updated_at": ckpt.get("updated_at", ""),
                "model": ckpt.get("model", ""),
            })
        except Exception:
            continue

    return {"checkpoints": result}
```

#### 2-6. 정적 파일 서빙 + 메인 페이지

```python
# 정적 파일 (CSS, JS 등)
app.mount("/static", StaticFiles(directory="static"), name="static")

# 메인 페이지 — index.html 반환
@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")
```

### 3. `translate.py` 수정사항

**변경 최소화 원칙** — 기존 CLI 동작은 그대로 유지하면서, 웹에서 호출할 때만 추가 기능 활성화.

```python
def run_pipeline(
    input_path: str,
    output_path: str,
    model: str,
    checkpoint_path: str,
    resume: bool,
    max_words: int,
    client: LLMClient,
    cancel_event: threading.Event | None = None,   # NEW — 기본 None (CLI 호환)
    log_handler: logging.Handler | None = None,     # NEW — 기본 None (CLI 호환)
) -> None:
```

**수정 포인트 3곳:**

```python
# (1) 함수 시작부: log_handler 등록
import threading  # 모듈 상단에 추가

def run_pipeline(...):
    start_time = time.time()

    # NEW: 웹 UI용 로그 핸들러 등록
    if log_handler:
        log_handler.setLevel(logging.INFO)
        logger.addHandler(log_handler)

    try:
        # ... 기존 로직 전체 ...
    finally:
        # NEW: 핸들러 정리
        if log_handler:
            logger.removeHandler(log_handler)
```

```python
    # (2) 번역 루프 내: 취소 체크 (for chunk in all_chunks: 루프 시작 직후)
    for chunk in all_chunks:
        # NEW: 취소 신호 확인
        if cancel_event and cancel_event.is_set():
            logger.info("사용자 요청으로 번역이 취소되었습니다.")
            break

        chunk_info = checkpoint_data["chunks"].get(chunk.id, {})
        # ... 기존 로직 ...
```

```python
    # (3) EPUB 빌드 전: 취소 시 빌드 스킵
    # 5. EPUB 빌드
    if cancel_event and cancel_event.is_set():
        logger.info("번역 취소됨 — EPUB 빌드를 건너뜁니다. 체크포인트는 저장되어 있습니다.")
        return

    logger.info("EPUB 빌드 시작...")
    # ... 기존 로직 ...
```

**수정하지 않는 것들:**
- `translate_chunk()` — 변경 없음
- `main()` (CLI 진입점) — 변경 없음
- `src/` 모듈 전체 — 변경 없음

---

## 데이터 플로우

### 전체 흐름: 업로드 → 번역 → 다운로드

```
사용자                       Browser (app.js)              Server (FastAPI)              Worker Thread
  │                              │                              │                              │
  │  파일 선택 + 설정             │                              │                              │
  ├─────────────────────────────>│                              │                              │
  │                              │ POST /api/translate          │                              │
  │                              │  (FormData: file+설정)       │                              │
  │                              ├─────────────────────────────>│                              │
  │                              │                              │  파일 저장 (uploads/)         │
  │                              │                              │  TaskInfo 생성                │
  │                              │                              │  LLMClient 초기화             │
  │                              │                              │  asyncio.to_thread 시작 ──────>│
  │                              │  {"task_id": "abc123"}       │                              │
  │                              │<─────────────────────────────│                              │
  │                              │                              │                              │
  │                              │ GET /api/progress/abc123     │                              │
  │                              │  (SSE EventSource 연결)      │                              │
  │                              ├─────────────────────────────>│                              │
  │                              │                              │                              │ run_pipeline()
  │                              │                              │                              │  ├ parse_epub()
  │                              │                              │                              │  ├ chunk_chapter()
  │                              │                              │                              │  ├ for chunk:
  │  진행률 원형 업데이트          │  event: progress             │  checkpoint 읽기              │  │  ├ cancel check
  │  로그 패널 업데이트            │  event: log                  │  log_buffer 읽기              │  │  ├ translate_chunk()
  │<─────────────────────────────│<─────────────────────────────│  (1초 주기 polling)           │  │  └ save_progress()
  │                              │                              │                              │  │
  │  [취소 버튼 클릭]             │                              │                              │  │
  ├─────────────────────────────>│ POST /api/cancel/abc123      │                              │  │
  │                              ├─────────────────────────────>│  cancel_event.set() ─────────>│  │ is_set()→True
  │                              │  {"status": "cancelling"}    │                              │  └ break
  │                              │<─────────────────────────────│                              │
  │                              │                              │                              │
  │                              │  event: done                 │                              │
  │  완료/취소 표시               │<─────────────────────────────│                              │
  │<─────────────────────────────│                              │                              │
  │                              │                              │                              │
  │  [다운로드 클릭]              │ GET /api/download/abc123     │                              │
  │                              ├─────────────────────────────>│                              │
  │  EPUB 파일 수신               │  FileResponse (EPUB)         │                              │
  │<─────────────────────────────│<─────────────────────────────│                              │
```

### SSE 이벤트 포맷

#### `event: progress` — 매 1초

```
event: progress
data: {
  "task_id": "abc123",
  "status": "running",
  "completed": 50,
  "total": 200,
  "failed": 0,
  "filename": "hitchhikers_guide.epub",
  "book_title": "hitchhikers_guide"
}
```

#### `event: log` — 새 로그 발생 시

```
event: log
data: {
  "time": "14:22:01",
  "level": "INFO",
  "message": "챕터 4 번역을 시작합니다."
}
```

#### `event: done` — 작업 완료/취소

```
event: done
data: {"output": "outputs/hitchhikers_guide_kr.epub"}
```

또는 취소 시:
```
event: done
data: {"status": "cancelled"}
```

#### `event: error` — 작업 실패

```
event: error
data: {"error": "MLX-LM 서버에 연결할 수 없습니다."}
```

---

## 프론트엔드 JavaScript 구조

### `static/app.js` 설계

```javascript
/**
 * EPUB Translator Studio — Frontend Controller
 *
 * 모듈 구조 (IIFE로 네임스페이스 격리):
 * - State: 현재 앱 상태
 * - API: 서버 통신
 * - UI: DOM 업데이트
 * - SSE: EventSource 관리
 * - Init: 이벤트 바인딩
 */

const App = (() => {
    // ─── State ──────────────────────────────────
    const state = {
        taskId: null,
        eventSource: null,
        status: 'idle',    // idle | uploading | running | completed | cancelled | failed
    };

    // ─── DOM References ─────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const dom = {
        // 업로드
        dropZone: $('#drop-zone'),
        fileInput: $('#file-input'),
        fileName: $('#file-name'),

        // 설정
        engineRadios: document.querySelectorAll('input[name="engine"]'),
        apiKeyInput: $('#api-key-input'),
        chunkSlider: $('#chunk-slider'),
        chunkValue: $('#chunk-value'),
        resumeCheck: $('#resume-check'),
        endpointInput: $('#endpoint-input'),

        // 액션 버튼
        translateBtn: $('#translate-btn'),
        cancelBtn: $('#cancel-btn'),
        downloadBtn: $('#download-btn'),

        // 진행률
        progressCircle: $('#progress-circle'),       // SVG circle
        progressText: $('#progress-text'),           // 64%
        progressDetail: $('#progress-detail'),       // #412 / #645
        bookTitle: $('#book-title'),

        // 로그
        logContainer: $('#log-container'),

        // 체크포인트
        checkpointList: $('#checkpoint-list'),
    };

    // ─── API ────────────────────────────────────
    const api = {
        async startTranslation(formData) {
            const res = await fetch('/api/translate', {
                method: 'POST',
                body: formData,
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || '번역 시작 실패');
            }
            return res.json();
        },

        async cancelTranslation(taskId) {
            const res = await fetch(`/api/cancel/${taskId}`, { method: 'POST' });
            return res.json();
        },

        async getCheckpoints() {
            const res = await fetch('/api/checkpoints');
            return res.json();
        },

        downloadUrl(taskId) {
            return `/api/download/${taskId}`;
        },
    };

    // ─── SSE ────────────────────────────────────
    const sse = {
        connect(taskId) {
            if (state.eventSource) state.eventSource.close();

            const es = new EventSource(`/api/progress/${taskId}`);
            state.eventSource = es;

            es.addEventListener('progress', (e) => {
                const data = JSON.parse(e.data);
                ui.updateProgress(data);
            });

            es.addEventListener('log', (e) => {
                const data = JSON.parse(e.data);
                ui.appendLog(data);
            });

            es.addEventListener('done', (e) => {
                const data = JSON.parse(e.data);
                if (data.status === 'cancelled') {
                    ui.setStatus('cancelled');
                } else {
                    ui.setStatus('completed');
                }
                es.close();
            });

            es.addEventListener('error', (e) => {
                // SSE 프로토콜 에러 vs 서버 에러 이벤트 구분
                if (e.data) {
                    const data = JSON.parse(e.data);
                    ui.showError(data.error);
                }
                ui.setStatus('failed');
                es.close();
            });

            es.onerror = () => {
                // 네트워크 끊김 — 3초 후 자동 재연결 (EventSource 기본 동작)
                // 별도 처리 불필요
            };
        },
    };

    // ─── UI ─────────────────────────────────────
    const ui = {
        updateProgress(data) {
            const pct = data.total > 0
                ? Math.round((data.completed / data.total) * 100)
                : 0;

            // SVG 원형 프로그레스
            const circumference = 2 * Math.PI * 58;  // r=58
            const offset = circumference - (pct / 100) * circumference;
            dom.progressCircle.style.strokeDashoffset = offset;

            // 텍스트 업데이트
            dom.progressText.textContent = `${pct}%`;
            dom.progressDetail.innerHTML =
                `처리 중인 청크: <span class="text-primary font-bold">#${data.completed} / #${data.total}</span>`;
            if (data.book_title) {
                dom.bookTitle.textContent = data.book_title;
            }
        },

        appendLog(entry) {
            // 로그 레벨별 스타일 매핑
            const levelStyles = {
                'INFO':    'bg-primary/10 text-primary',
                'WARNING': 'bg-[#ff9800]/10 text-[#ff9800]',
                'ERROR':   'bg-error/10 text-error',
                'DEBUG':   'bg-outline/10 text-outline',
            };
            const style = levelStyles[entry.level] || levelStyles['INFO'];

            const html = `
                <div class="flex gap-3 text-sm font-['Manrope']">
                    <span class="text-outline-variant font-mono">${entry.time}</span>
                    <span class="px-1.5 py-0.5 rounded ${style} text-[10px] font-bold h-fit">[${entry.level}]</span>
                    <p class="text-on-surface-variant">${entry.message}</p>
                </div>`;

            dom.logContainer.insertAdjacentHTML('afterbegin', html);

            // 최대 200개 로그 유지 (DOM 메모리 관리)
            while (dom.logContainer.children.length > 200) {
                dom.logContainer.removeChild(dom.logContainer.lastChild);
            }
        },

        setStatus(status) {
            state.status = status;
            // 버튼 상태 토글
            const isRunning = status === 'running';
            dom.translateBtn.disabled = isRunning;
            dom.cancelBtn.classList.toggle('hidden', !isRunning);
            dom.downloadBtn.classList.toggle('hidden', status !== 'completed');
        },

        showError(message) {
            this.appendLog({
                time: new Date().toLocaleTimeString('ko-KR', { hour12: false }),
                level: 'ERROR',
                message: message,
            });
        },

        async loadCheckpoints() {
            const { checkpoints } = await api.getCheckpoints();
            dom.checkpointList.innerHTML = checkpoints.map(cp => {
                const pct = cp.total > 0 ? Math.round((cp.completed / cp.total) * 100) : 0;
                return `
                    <div class="bg-surface-container-high p-4 rounded-xl border border-outline-variant/10 flex items-center gap-4">
                        <div class="w-12 h-12 rounded-lg bg-surface-container-highest flex items-center justify-center text-primary">
                            <span class="material-symbols-outlined">${pct === 100 ? 'check_circle' : 'description'}</span>
                        </div>
                        <div class="flex-1">
                            <p class="text-sm font-bold text-on-surface">${cp.filename}</p>
                            <div class="flex items-center gap-2 mt-1">
                                <div class="flex-1 h-1 bg-surface-container rounded-full overflow-hidden">
                                    <div class="h-full bg-primary/60" style="width:${pct}%"></div>
                                </div>
                                <span class="text-[10px] font-bold text-primary">${pct}%</span>
                            </div>
                        </div>
                    </div>`;
            }).join('');
        },
    };

    // ─── Init ───────────────────────────────────
    function init() {
        // 파일 드래그앤드롭
        dom.dropZone.addEventListener('click', () => dom.fileInput.click());
        dom.dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dom.dropZone.classList.add('border-primary/50');
        });
        dom.dropZone.addEventListener('dragleave', () => {
            dom.dropZone.classList.remove('border-primary/50');
        });
        dom.dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dom.dropZone.classList.remove('border-primary/50');
            if (e.dataTransfer.files.length) {
                dom.fileInput.files = e.dataTransfer.files;
                dom.fileName.textContent = e.dataTransfer.files[0].name;
            }
        });
        dom.fileInput.addEventListener('change', () => {
            if (dom.fileInput.files.length) {
                dom.fileName.textContent = dom.fileInput.files[0].name;
            }
        });

        // 청크 슬라이더
        dom.chunkSlider.addEventListener('input', () => {
            dom.chunkValue.textContent = `${Number(dom.chunkSlider.value).toLocaleString()} chars`;
        });

        // 번역 시작
        dom.translateBtn.addEventListener('click', async () => {
            if (!dom.fileInput.files.length) {
                alert('EPUB 파일을 선택하세요.');
                return;
            }

            const formData = new FormData();
            formData.append('file', dom.fileInput.files[0]);
            formData.append('provider', getSelectedEngine());
            formData.append('api_key', dom.apiKeyInput.value);
            formData.append('endpoint', dom.endpointInput.value);
            formData.append('max_words', dom.chunkSlider.value);
            formData.append('resume', dom.resumeCheck.checked);

            ui.setStatus('uploading');
            try {
                const { task_id } = await api.startTranslation(formData);
                state.taskId = task_id;
                ui.setStatus('running');
                sse.connect(task_id);
            } catch (e) {
                ui.showError(e.message);
                ui.setStatus('failed');
            }
        });

        // 취소
        dom.cancelBtn.addEventListener('click', async () => {
            if (state.taskId) {
                await api.cancelTranslation(state.taskId);
            }
        });

        // 다운로드
        dom.downloadBtn.addEventListener('click', () => {
            if (state.taskId) {
                window.location.href = api.downloadUrl(state.taskId);
            }
        });

        // 초기 체크포인트 로드
        ui.loadCheckpoints();
    }

    function getSelectedEngine() {
        for (const radio of dom.engineRadios) {
            if (radio.checked) {
                return radio.value;
            }
        }
        return 'local';
    }

    // ─── Boot ───────────────────────────────────
    document.addEventListener('DOMContentLoaded', init);

    return { state, api, ui, sse };
})();
```

### `static/index.html` 수정 포인트 (code.html 대비)

code.html을 기반으로 다음 id/속성만 추가. 디자인은 그대로 유지한다.

| 위치 | 추가할 속성 | 용도 |
|------|-----------|------|
| 파일 업로드 영역 `<div>` | `id="drop-zone"` | 드래그앤드롭 바인딩 |
| 숨겨진 `<input type="file">` | `id="file-input" accept=".epub"` | 파일 선택 (새로 추가) |
| 파일명 표시 `<p>` | `id="file-name"` | 선택된 파일명 표시 |
| 엔진 라디오 `<input>` | `value="local"`, `value="openai"`, `value="claude"` | 엔진 식별 |
| API 키 `<input>` | `id="api-key-input"` | API 키 입력 |
| 엔드포인트 `<input>` | `id="endpoint-input"` (새로 추가) | 로컬 서버 엔드포인트 |
| 청크 슬라이더 `<input>` | `id="chunk-slider"` | 청크 크기 |
| 청크 값 표시 `<span>` | `id="chunk-value"` | 슬라이더 값 표시 |
| 이어하기 체크박스 | `id="resume-check"` | 이미 존재 (`id="resume"`) |
| 번역 시작 버튼 | `id="translate-btn"` | 번역 시작 |
| SVG 프로그레스 circle | `id="progress-circle"` | 원형 프로그레스 |
| 퍼센트 텍스트 | `id="progress-text"` | 64% → 동적 |
| 청크 진행 `<p>` | `id="progress-detail"` | #412 / #645 |
| 책 제목 `<h3>` | `id="book-title"` | 동적 책 제목 |
| 다운로드 버튼 | `id="download-btn"` + `class="hidden"` | 초기 숨김 |
| 중단 버튼 | `id="cancel-btn"` + `class="hidden"` | 초기 숨김 |
| 로그 컨테이너 `<div>` | `id="log-container"` | 로그 삽입 위치 |
| 체크포인트 리스트 `<div>` | `id="checkpoint-list"` | 체크포인트 카드 |

---

## 에러 처리

### 에러 분류 및 대응

| 에러 시나리오 | 발생 위치 | 감지 방법 | 사용자 피드백 | 복구 전략 |
|-------------|----------|----------|-------------|----------|
| **EPUB이 아닌 파일 업로드** | server.py | 확장자 체크 | HTTP 400 + 에러 메시지 | 재업로드 안내 |
| **50MB 초과 파일** | server.py | Content-Length 체크 | HTTP 413 | 파일 분할 안내 |
| **LLM 서버 미실행** | server.py | `client.check_connection()` | HTTP 503 + 서버 시작 명령 | 서버 시작 후 재시도 |
| **API 키 무효** | translate_chunk() | API 응답 401 | SSE error 이벤트 | 키 재입력 |
| **LLM 응답 빈 문자열** | translator.py | 기존 재시도 로직 | SSE log WARNING | 자동 재시도 (3회) |
| **LLM 타임아웃** | translator.py | httpx Timeout | SSE log WARNING | exponential backoff |
| **SSE 연결 끊김** | Browser | EventSource.onerror | 자동 재연결 (브라우저 내장) | EventSource 자동 재연결 |
| **번역 중 서버 크래시** | 전체 | 프로세스 종료 | 페이지 접속 불가 | 체크포인트 보존 → resume |
| **중복 번역 요청** | server.py | 동일 파일 체크 | 기존 task_id 반환 + 경고 | SSE 재연결 |

### SSE 재연결 전략

```
EventSource 기본 동작:
  - 연결 끊김 → 자동 재연결 (보통 3초 후)
  - 서버가 Last-Event-Id 헤더를 지원하면 이어받기 가능

Phase 2 구현:
  - Last-Event-Id는 구현하지 않음 (과잉)
  - 재연결 시 체크포인트에서 현재 상태를 다시 읽음 → 자연스럽게 동기화
  - 5회 재연결 실패 시 → 수동 새로고침 안내 표시
```

### 파일 정리 정책

```
uploads/    → 번역 완료/실패 후 24시간 뒤 자동 삭제 (Phase 3)
              Phase 2에서는 수동 관리
outputs/    → 다운로드 후 수동 삭제
              서버 재시작 시에도 유지
checkpoints/ → 기존 정책 유지 (resume용)
```

---

## UI/UX

### 자체 구현 (단순 UI)

code.html 디자인을 그대로 사용하며, 동적 바인딩만 추가한다.

**디자인 시스템 준수 사항 (DESIGN.md):**
- 색상: 네이비 베이스 `#040e1f` + 사파이어 `#85adff` — Tailwind config 유지
- 글꼴: Manrope CDN — 기존 유지
- 유리 효과: `.glass-panel` 클래스 — 기존 유지
- CTA 버튼: `.btn-primary-gradient` — 기존 유지
- 보더 금지: 배경 톤 시프트로 경계 표현 — 기존 유지

**추가 UI 요소:**
1. 숨겨진 `<input type="file" id="file-input">` — 드롭존 클릭 시 트리거
2. 엔드포인트 입력 필드 — 왼쪽 패널 API 키 아래
3. 모델 선택 필드 — 왼쪽 패널 (빈칸 = 프로바이더별 기본)

**반응형:** code.html의 `lg:grid-cols-12` 그리드 + 모바일 하단 네비 그대로 유지.

---

## 구현 순서

의존성 기반으로 정렬. 각 단계가 완료되면 다음으로 진행한다.

### Step 1: `translate.py` 수정 (30분)

**파일:** `translate.py`
**변경:**
- `import threading` 추가
- `run_pipeline()` 시그니처에 `cancel_event`, `log_handler` 파라미터 추가 (기본 None)
- 번역 루프 내 `cancel_event.is_set()` 체크 (3줄)
- EPUB 빌드 전 취소 체크 (3줄)
- `log_handler` 등록/해제 (try/finally, 5줄)

**검증:** 기존 CLI `python translate.py input.epub` 동작 확인 (cancel_event=None이면 기존과 동일)

### Step 2: `task_manager.py` 생성 (30분)

**파일:** `task_manager.py`
**내용:** TaskInfo, TaskStatus, BufferLogHandler, 전역 저장소, CRUD 함수

**검증:** 단위 테스트 — TaskInfo 생성, cancel, log_handler 동작

### Step 3: `server.py` 생성 (1시간)

**파일:** `server.py`
**내용:** FastAPI 앱, 5개 엔드포인트, 정적 파일 서빙

**검증:** `uvicorn server:app --reload`로 기동 후 `/api/checkpoints` 응답 확인

### Step 4: `static/index.html` 생성 (1시간)

**파일:** `static/index.html`
**내용:** code.html 기반 + id 속성 추가 + `<input type="file">` 추가 + 엔드포인트 필드 추가 + `<script src="/static/app.js">` 삽입

**검증:** `http://localhost:8000` 접속하여 디자인 렌더링 확인

### Step 5: `static/app.js` 생성 (2시간)

**파일:** `static/app.js`
**내용:** IIFE 모듈 — State, API, SSE, UI, Init

**검증:**
1. 파일 드래그앤드롭 동작
2. 번역 시작 → SSE 연결 → 프로그레스 업데이트
3. 취소 버튼 동작
4. 완료 후 다운로드

### Step 6: `requirements.txt` + `run.sh` 수정 (10분)

**requirements.txt:**
```
ebooklib>=0.18
beautifulsoup4>=4.12
lxml>=4.9
openai>=1.0
anthropic>=0.25
tqdm>=4.65
httpx>=0.27
fastapi>=0.115
uvicorn>=0.28
python-multipart>=0.0.9
```

**run.sh:**
```bash
#!/bin/bash
set -e
if [ ! -f "venv/bin/python3" ]; then
    echo "가상환경이 없습니다. 먼저 설치를 실행하세요: ./install.sh"
    exit 1
fi
echo ""
echo "EPUB Translator Studio 시작 중..."
echo "브라우저에서 http://localhost:8000 이 자동으로 열립니다."
echo "(종료: Ctrl+C)"
echo ""
./venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

### Step 7: 통합 테스트 (1시간)

1. 실제 EPUB 파일로 번역 시작 → 완료 → 다운로드
2. 번역 중 취소 → 체크포인트 보존 확인
3. 취소 후 resume 체크 → 이어하기 동작 확인
4. SSE 연결 끊김 → 자동 재연결 확인
5. 잘못된 파일 업로드 → 에러 메시지 확인

---

## 설계 결정 근거

### 1. `asyncio.to_thread` vs `asyncio.create_task` + async 래퍼

| 기준 | to_thread | create_task + async |
|------|-----------|-------------------|
| 기존 코드 변경량 | **최소** (파라미터 2개 추가) | 대규모 (전체 async화) |
| 이벤트 루프 블로킹 | 없음 (별도 스레드) | 없음 |
| 취소 메커니즘 | threading.Event | asyncio.Event |
| 디버깅 용이성 | **높음** (동기 코드 유지) | 낮음 (async 스택트레이스) |
| CLI 호환성 | **유지** | 깨짐 (async 진입점 필요) |

**결론:** `asyncio.to_thread` 선택. 기존 코드 변경 최소화 + CLI 호환성 유지.

### 2. SSE vs WebSocket

리서치 결과 그대로 채택. 진행률/로그는 서버→클라이언트 단방향이므로 SSE 최적.

### 3. 전역 딕셔너리 vs Redis/DB

단일 프로세스, 단일 사용자 시나리오. Redis는 과잉. 서버 재시작 시 작업 상태는 사라지지만, 체크포인트 파일은 보존되므로 resume로 복구 가능.

### 4. `log_buffer` (deque) vs 파일 기반 로그 스트리밍

- deque: 메모리 내, maxlen=500으로 제한, 빠른 접근
- 파일: 디스크 I/O, 파일 tail 구현 필요
- **deque 선택** — 단순성, 성능. 500개 로그 * ~100바이트 = ~50KB (무시 가능)

### 5. 프론트엔드 프레임워크 없음

React/Vue 도입 시: 빌드 파이프라인, node_modules, 번들러 필요.
Vanilla JS: HTML 파일 하나 + JS 파일 하나. 디자인 HTML 그대로 사용 가능.
이 프로젝트의 UI 복잡도(폼 1개 + 프로그레스 + 로그)에서 프레임워크는 과잉.
