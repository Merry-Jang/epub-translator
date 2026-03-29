"""번역 작업 생명주기 관리 — TaskInfo, 전역 저장소, 로그 버퍼."""

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"         # 생성됨, 세마포어 대기 중
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
            "time": self._format_time(record),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        self.log_buffer.append(entry)

    @staticmethod
    def _format_time(record: logging.LogRecord) -> str:
        return datetime.fromtimestamp(record.created).strftime("%H:%M:%S")


# 전역 작업 저장소
_tasks: dict[str, TaskInfo] = {}


def create_task(
    task_id: str,
    filename: str,
    input_path: str,
    output_path: str,
    checkpoint_path: str,
) -> TaskInfo:
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


def get_all_tasks() -> dict[str, TaskInfo]:
    """전역 작업 딕셔너리 참조를 반환한다 (cleanup용)."""
    return _tasks


def cancel_task(task_id: str) -> bool:
    """작업 취소 신호를 보낸다. 존재하고 RUNNING이면 True."""
    task = _tasks.get(task_id)
    if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        task.cancel_event.set()
        return True
    return False
