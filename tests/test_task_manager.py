"""task_manager.py 단위 테스트 — TaskInfo, 저장소 함수, BufferLogHandler."""

import logging
import threading
from collections import deque
from datetime import datetime

import pytest

import task_manager as tm
from task_manager import (
    BufferLogHandler,
    TaskInfo,
    TaskStatus,
    cancel_task,
    create_task,
    get_all_tasks,
    get_task,
    remove_task,
)


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_task_store():
    """각 테스트 전후 전역 _tasks 저장소를 초기화한다."""
    tm._tasks.clear()
    yield
    tm._tasks.clear()


def make_task(task_id: str = "abc123", **kwargs) -> TaskInfo:
    """테스트용 TaskInfo 생성 헬퍼."""
    defaults = dict(
        task_id=task_id,
        filename="test.epub",
        input_path="uploads/test.epub",
        output_path="outputs/test_kr.epub",
        checkpoint_path="checkpoints/test_progress.json",
    )
    defaults.update(kwargs)
    return create_task(**defaults)


# ─────────────────────────────────────────────
# TaskStatus
# ─────────────────────────────────────────────

class TestTaskStatus:
    def test_values_are_strings(self):
        """TaskStatus 값은 문자열이다 (JSON 직렬화 호환)."""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.CANCELLED.value == "cancelled"
        assert TaskStatus.FAILED.value == "failed"

    def test_str_enum_equality(self):
        """TaskStatus는 str과 직접 비교 가능하다."""
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.COMPLETED == "completed"


# ─────────────────────────────────────────────
# TaskInfo 생성 및 필드 검증
# ─────────────────────────────────────────────

class TestTaskInfo:
    def test_default_status_is_pending(self):
        task = make_task()
        assert task.status == TaskStatus.PENDING

    def test_cancel_event_is_threading_event(self):
        task = make_task()
        assert isinstance(task.cancel_event, threading.Event)
        assert not task.cancel_event.is_set()

    def test_log_buffer_is_deque_with_maxlen_500(self):
        task = make_task()
        assert isinstance(task.log_buffer, deque)
        assert task.log_buffer.maxlen == 500

    def test_created_at_is_datetime(self):
        task = make_task()
        assert isinstance(task.created_at, datetime)

    def test_initial_chunk_counts_are_zero(self):
        task = make_task()
        assert task.total_chunks == 0
        assert task.completed_chunks == 0
        assert task.failed_chunks == 0

    def test_error_message_default_empty(self):
        task = make_task()
        assert task.error_message == ""

    def test_status_mutation(self):
        """status 필드를 직접 변경할 수 있다."""
        task = make_task()
        task.status = TaskStatus.RUNNING
        assert task.status == TaskStatus.RUNNING

    def test_each_task_has_independent_cancel_event(self):
        """두 TaskInfo의 cancel_event는 서로 독립적이다."""
        task_a = make_task("id_a")
        task_b = make_task("id_b")
        task_a.cancel_event.set()
        assert task_a.cancel_event.is_set()
        assert not task_b.cancel_event.is_set()

    def test_each_task_has_independent_log_buffer(self):
        """두 TaskInfo의 log_buffer는 서로 독립적이다."""
        task_a = make_task("id_a")
        task_b = make_task("id_b")
        task_a.log_buffer.append({"msg": "only in a"})
        assert len(task_a.log_buffer) == 1
        assert len(task_b.log_buffer) == 0


# ─────────────────────────────────────────────
# create_task
# ─────────────────────────────────────────────

class TestCreateTask:
    def test_returns_task_info(self):
        task = make_task("t1")
        assert isinstance(task, TaskInfo)

    def test_task_registered_in_store(self):
        make_task("t1")
        assert get_task("t1") is not None

    def test_task_fields_set_correctly(self):
        task = make_task("t1")
        assert task.task_id == "t1"
        assert task.filename == "test.epub"

    def test_duplicate_id_overwrites(self):
        """같은 task_id로 두 번 생성하면 마지막 것으로 덮어쓴다."""
        task_a = create_task("dup", "a.epub", "in/a", "out/a", "ck/a")
        task_b = create_task("dup", "b.epub", "in/b", "out/b", "ck/b")
        assert get_task("dup") is task_b


# ─────────────────────────────────────────────
# get_task
# ─────────────────────────────────────────────

class TestGetTask:
    def test_returns_task_for_existing_id(self):
        make_task("t1")
        result = get_task("t1")
        assert result is not None
        assert result.task_id == "t1"

    def test_returns_none_for_missing_id(self):
        result = get_task("nonexistent")
        assert result is None

    def test_returns_same_object_reference(self):
        """get_task는 저장된 같은 객체를 반환한다 (복사 아님)."""
        original = make_task("t1")
        retrieved = get_task("t1")
        assert original is retrieved


# ─────────────────────────────────────────────
# get_all_tasks
# ─────────────────────────────────────────────

class TestGetAllTasks:
    def test_returns_empty_dict_initially(self):
        result = get_all_tasks()
        assert result == {}

    def test_returns_all_registered_tasks(self):
        make_task("t1")
        make_task("t2")
        result = get_all_tasks()
        assert set(result.keys()) == {"t1", "t2"}

    def test_returns_shallow_copy(self):
        """get_all_tasks()가 반환한 딕셔너리를 수정해도 원본에 영향이 없다."""
        make_task("t1")
        copy = get_all_tasks()
        copy["new_key"] = "injected"
        assert get_task("new_key") is None

    def test_values_are_task_info_instances(self):
        make_task("t1")
        result = get_all_tasks()
        assert isinstance(result["t1"], TaskInfo)


# ─────────────────────────────────────────────
# remove_task
# ─────────────────────────────────────────────

class TestRemoveTask:
    def test_removes_existing_task(self):
        make_task("t1")
        remove_task("t1")
        assert get_task("t1") is None

    def test_returns_removed_task(self):
        original = make_task("t1")
        removed = remove_task("t1")
        assert removed is original

    def test_returns_none_for_missing_id(self):
        result = remove_task("nonexistent")
        assert result is None

    def test_remove_does_not_affect_other_tasks(self):
        make_task("t1")
        make_task("t2")
        remove_task("t1")
        assert get_task("t2") is not None


# ─────────────────────────────────────────────
# cancel_task
# ─────────────────────────────────────────────

class TestCancelTask:
    def test_cancel_pending_task_returns_true(self):
        make_task("t1")  # default status: PENDING
        result = cancel_task("t1")
        assert result is True

    def test_cancel_running_task_returns_true(self):
        task = make_task("t1")
        task.status = TaskStatus.RUNNING
        result = cancel_task("t1")
        assert result is True

    def test_cancel_sets_cancel_event(self):
        make_task("t1")
        cancel_task("t1")
        task = get_task("t1")
        assert task.cancel_event.is_set()

    def test_cancel_completed_task_returns_false(self):
        task = make_task("t1")
        task.status = TaskStatus.COMPLETED
        result = cancel_task("t1")
        assert result is False

    def test_cancel_failed_task_returns_false(self):
        task = make_task("t1")
        task.status = TaskStatus.FAILED
        result = cancel_task("t1")
        assert result is False

    def test_cancel_nonexistent_task_returns_false(self):
        result = cancel_task("nonexistent")
        assert result is False

    def test_cancel_cancelled_task_returns_false(self):
        task = make_task("t1")
        task.status = TaskStatus.CANCELLED
        result = cancel_task("t1")
        assert result is False


# ─────────────────────────────────────────────
# BufferLogHandler
# ─────────────────────────────────────────────

class TestBufferLogHandler:
    def _make_handler(self) -> tuple[BufferLogHandler, deque]:
        buf = deque(maxlen=500)
        handler = BufferLogHandler(buf)
        handler.setLevel(logging.DEBUG)
        return handler, buf

    def test_emit_appends_to_buffer(self):
        handler, buf = self._make_handler()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="hello world",
            args=(), exc_info=None,
        )
        handler.emit(record)
        assert len(buf) == 1

    def test_emitted_entry_has_required_keys(self):
        handler, buf = self._make_handler()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="test message",
            args=(), exc_info=None,
        )
        handler.emit(record)
        entry = buf[0]
        assert "time" in entry
        assert "level" in entry
        assert "message" in entry

    def test_emitted_entry_level_matches(self):
        handler, buf = self._make_handler()
        for level, expected in [
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
        ]:
            record = logging.LogRecord(
                name="test", level=level,
                pathname="", lineno=0, msg="msg",
                args=(), exc_info=None,
            )
            handler.emit(record)

        levels = [e["level"] for e in buf]
        assert "INFO" in levels
        assert "WARNING" in levels
        assert "ERROR" in levels

    def test_emitted_entry_message_content(self):
        handler, buf = self._make_handler()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="번역 중: %s",
            args=("chapter1",), exc_info=None,
        )
        handler.emit(record)
        assert buf[0]["message"] == "번역 중: chapter1"

    def test_buffer_maxlen_respected(self):
        """maxlen=5 버퍼에 10개 emit 시 마지막 5개만 남는다."""
        buf = deque(maxlen=5)
        handler = BufferLogHandler(buf)
        for i in range(10):
            record = logging.LogRecord(
                name="test", level=logging.INFO,
                pathname="", lineno=0, msg=f"msg {i}",
                args=(), exc_info=None,
            )
            handler.emit(record)
        assert len(buf) == 5
        assert buf[-1]["message"] == "msg 9"

    def test_format_time_returns_hhmmss_string(self):
        """_format_time은 HH:MM:SS 포맷 문자열을 반환한다."""
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="time test",
            args=(), exc_info=None,
        )
        result = BufferLogHandler._format_time(record)
        # HH:MM:SS 포맷 검증
        parts = result.split(":")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_handler_attached_to_logger(self):
        """실제 logger에 핸들러를 붙였을 때 로그가 버퍼에 저장된다."""
        handler, buf = self._make_handler()
        test_logger = logging.getLogger("test_pipeline_logger")
        test_logger.setLevel(logging.INFO)
        test_logger.addHandler(handler)
        try:
            test_logger.info("pipeline started")
            assert len(buf) == 1
            assert buf[0]["message"] == "pipeline started"
        finally:
            test_logger.removeHandler(handler)

    def test_handler_removed_stops_capture(self):
        """핸들러 제거 후에는 로그가 버퍼에 추가되지 않는다."""
        handler, buf = self._make_handler()
        test_logger = logging.getLogger("test_remove_logger")
        test_logger.setLevel(logging.INFO)
        test_logger.addHandler(handler)
        test_logger.info("before remove")
        test_logger.removeHandler(handler)
        test_logger.info("after remove")
        assert len(buf) == 1
        assert buf[0]["message"] == "before remove"


# ─────────────────────────────────────────────
# cancel_event 동작 (threading.Event)
# ─────────────────────────────────────────────

class TestCancelEventBehavior:
    def test_event_starts_unset(self):
        task = make_task()
        assert not task.cancel_event.is_set()

    def test_set_event_is_detected(self):
        task = make_task()
        task.cancel_event.set()
        assert task.cancel_event.is_set()

    def test_cancel_event_can_be_cleared(self):
        task = make_task()
        task.cancel_event.set()
        task.cancel_event.clear()
        assert not task.cancel_event.is_set()

    def test_cancel_event_checked_in_loop(self):
        """cancel_event 체크 패턴 — 루프 중단 시뮬레이션."""
        task = make_task()
        processed = []

        for i in range(10):
            if task.cancel_event.is_set():
                break
            processed.append(i)
            if i == 4:
                task.cancel_event.set()

        # i=4에서 set, 다음 반복(i=5)에서 break → processed=[0,1,2,3,4]
        assert processed == [0, 1, 2, 3, 4]
