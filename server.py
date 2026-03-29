"""EPUB Translator Studio — FastAPI 메인 앱."""

import asyncio
import glob as glob_mod
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.checkpoint import load_progress
from src.providers import DEFAULT_MODELS, LLMClient
from task_manager import (
    BufferLogHandler,
    TaskStatus,
    cancel_task,
    create_task,
    get_all_tasks,
    get_task,
    remove_task,
)
from translate import run_pipeline

logger = logging.getLogger(__name__)

app = FastAPI(title="EPUB Translator Studio")

# CORS (로컬 전용)
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 디렉토리 설정
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
CHECKPOINT_DIR = "checkpoints"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

# 동시 번역 제한 [필수 #4]
MAX_CONCURRENT = 2
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB [필수 #2]

_translation_semaphore: asyncio.Semaphore | None = None


@app.on_event("startup")
async def startup():
    """앱 시작 시 세마포어 초기화 + 클린업 태스크 등록."""
    global _translation_semaphore
    _translation_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    asyncio.create_task(_cleanup_loop())


async def _cleanup_loop():
    """완료된 작업과 임시 파일을 24시간 후 정리. [필수 #5]"""
    while True:
        await asyncio.sleep(3600)  # 1시간마다 실행
        now = datetime.now()
        terminal_statuses = {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED}
        to_remove = []

        tasks = get_all_tasks()
        for task_id, task in list(tasks.items()):
            if task.status in terminal_statuses:
                age = (now - task.created_at).total_seconds()
                if age > 86400:  # 24시간
                    to_remove.append(task_id)

        for task_id in to_remove:
            task = remove_task(task_id)
            if task:
                # 업로드·출력·체크포인트 파일 삭제
                for path_attr in ("input_path", "output_path", "checkpoint_path"):
                    path = getattr(task, path_attr, None)
                    if path and os.path.exists(path):
                        try:
                            os.unlink(path)
                            logger.info("임시 파일 삭제: %s", path)
                        except OSError as e:
                            logger.warning("파일 삭제 실패: %s — %s", path, e)

        if to_remove:
            logger.info("클린업 완료: %d개 작업 제거", len(to_remove))


# ──────────────────────────────────────────────
# API 엔드포인트
# ──────────────────────────────────────────────


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
    """EPUB 파일을 업로드하고 번역 작업을 시작한다."""
    # 1. 파일 검증
    if not file.filename or not file.filename.lower().endswith(".epub"):
        raise HTTPException(400, "EPUB 파일만 업로드 가능합니다.")

    # 2. 안전한 파일명 추출 [필수 #1]
    safe_name = Path(file.filename).name
    task_id = str(uuid.uuid4())[:12]  # [권장 #6] 12자
    stem = Path(safe_name).stem

    input_path = os.path.join(UPLOAD_DIR, f"{task_id}_{safe_name}")
    output_path = os.path.join(OUTPUT_DIR, f"{task_id}_{stem}_kr.epub")  # [권장 #7]
    checkpoint_path = os.path.join(CHECKPOINT_DIR, f"{task_id}_{stem}_progress.json")

    # 3. 파일 크기 제한 [필수 #2]
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            413,
            f"파일이 50MB를 초과합니다 ({len(content) // (1024 * 1024)}MB).",
        )

    with open(input_path, "wb") as f:
        f.write(content)

    # 4. TaskInfo 생성
    task = create_task(task_id, safe_name, input_path, output_path, checkpoint_path)

    # 5. 모델/클라이언트 준비
    actual_model = model.strip() or DEFAULT_MODELS.get(provider, "")
    if not actual_model:
        task.status = TaskStatus.FAILED
        task.error_message = f"지원하지 않는 프로바이더: {provider}"
        raise HTTPException(400, task.error_message)

    ep = endpoint.strip() or None
    key = api_key.strip() or None

    try:
        client = LLMClient(provider=provider, api_key=key, endpoint=ep)
    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error_message = f"클라이언트 초기화 실패: {e}"
        raise HTTPException(400, task.error_message)

    # 6. 로컬 서버 연결 확인 (동기 I/O를 to_thread로 래핑)
    if provider == "local":
        connected = await asyncio.to_thread(client.check_connection)
        if not connected:
            task.status = TaskStatus.FAILED
            task.error_message = "MLX-LM 서버에 연결할 수 없습니다."
            raise HTTPException(503, task.error_message)

    # 7. 체크포인트 존재 시 자동 resume
    if os.path.exists(checkpoint_path) and not resume:
        ckpt = load_progress(checkpoint_path)
        if ckpt:
            done = ckpt.get("completed_chunks", 0)
            total = ckpt.get("total_chunks", 0)
            if 0 < done < total:
                resume = True

    # 8. 백그라운드 번역 시작 (세마포어 제한) [필수 #4]
    async def _run_in_background():
        async with _translation_semaphore:
            if task.cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
                return

            task.status = TaskStatus.RUNNING
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
                    cancel_event=task.cancel_event,
                    log_handler=log_handler,
                )
                if task.cancel_event.is_set():
                    task.status = TaskStatus.CANCELLED
                else:
                    task.status = TaskStatus.COMPLETED
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                logger.error("번역 작업 실패 [%s]: %s", task_id, e)

    asyncio.create_task(_run_in_background())

    return {
        "task_id": task_id,
        "status": task.status.value,
        "filename": safe_name,
    }


@app.get("/api/progress/{task_id}")
async def stream_progress(task_id: str):
    """SSE 스트리밍으로 진행률과 로그를 실시간 전송한다."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")

    async def event_generator():
        log_cursor = 0

        while True:
            # 체크포인트에서 진행률 읽기 [필수 #3]
            ckpt = await asyncio.to_thread(load_progress, task.checkpoint_path)
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

            # 새 로그 전송 [권장 #9] 단일 스냅샷 패턴
            snapshot = list(task.log_buffer)
            if len(snapshot) > log_cursor:
                new_logs = snapshot[log_cursor:]
                for log_entry in new_logs:
                    yield f"event: log\ndata: {json.dumps(log_entry, ensure_ascii=False)}\n\n"
                log_cursor = len(snapshot)

            # 종료 조건 확인
            if task.status == TaskStatus.COMPLETED:
                yield f"event: done\ndata: {json.dumps({'output': task.output_path})}\n\n"
                break
            elif task.status == TaskStatus.CANCELLED:
                yield f"event: done\ndata: {json.dumps({'status': 'cancelled'})}\n\n"
                break
            elif task.status == TaskStatus.FAILED:
                yield f"event: error\ndata: {json.dumps({'error': task.error_message}, ensure_ascii=False)}\n\n"
                break

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/cancel/{task_id}")
async def cancel_translation(task_id: str):
    """진행 중인 번역을 취소한다."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")

    if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(400, f"취소할 수 없는 상태: {task.status.value}")

    cancel_task(task_id)

    return {
        "task_id": task_id,
        "status": "cancelling",
        "message": "취소 신호를 보냈습니다. 현재 청크 완료 후 중단됩니다.",
    }


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


def _load_checkpoints_sync() -> list[dict]:
    """체크포인트 파일 목록을 동기적으로 읽는다 (to_thread용)."""
    files = glob_mod.glob(os.path.join(CHECKPOINT_DIR, "*_progress.json"))
    result = []

    for f in sorted(files, key=os.path.getmtime, reverse=True):
        try:
            ckpt = load_progress(f)
            if not ckpt:
                continue
            total = ckpt.get("total_chunks", 0)
            completed = ckpt.get("completed_chunks", 0)
            result.append({
                "filename": Path(ckpt.get("source", "")).name,
                "total": total,
                "completed": completed,
                "failed": ckpt.get("failed_chunks", 0),
                "updated_at": ckpt.get("updated_at", ""),
                "model": ckpt.get("model", ""),
            })
        except Exception:
            continue

    return result


@app.get("/api/checkpoints")
async def list_checkpoints():
    """저장된 체크포인트 목록을 반환한다."""
    result = await asyncio.to_thread(_load_checkpoints_sync)
    return {"checkpoints": result}


# ──────────────────────────────────────────────
# 정적 파일 서빙 + 메인 페이지
# ──────────────────────────────────────────────

@app.get("/")
async def serve_index():
    """메인 페이지 — index.html 반환."""
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
