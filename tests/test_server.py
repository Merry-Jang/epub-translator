"""server.py 통합 테스트 — FastAPI TestClient (httpx) 사용."""

import io
import json
import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import task_manager as tm
from task_manager import TaskStatus


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_task_store():
    """각 테스트 전후 전역 _tasks 저장소를 초기화한다."""
    tm._tasks.clear()
    yield
    tm._tasks.clear()


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient — 모듈 스코프로 한 번만 생성."""
    from server import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def minimal_epub_bytes() -> bytes:
    """유효한 EPUB 구조를 흉내 낸 최소 ZIP 바이트를 반환한다."""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", "<container/>")
        zf.writestr("content.opf", "<package/>")
    return buf.getvalue()


# ─────────────────────────────────────────────
# GET /
# ─────────────────────────────────────────────

class TestServeIndex:
    def test_get_root_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_get_root_returns_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.headers.get("content-type", "")


# ─────────────────────────────────────────────
# GET /api/checkpoints
# ─────────────────────────────────────────────

class TestListCheckpoints:
    def test_returns_200(self, client):
        resp = client.get("/api/checkpoints")
        assert resp.status_code == 200

    def test_returns_json_with_checkpoints_key(self, client):
        resp = client.get("/api/checkpoints")
        body = resp.json()
        assert "checkpoints" in body

    def test_checkpoints_is_list(self, client):
        resp = client.get("/api/checkpoints")
        body = resp.json()
        assert isinstance(body["checkpoints"], list)

    def test_checkpoints_empty_when_no_files(self, client, tmp_path, monkeypatch):
        """체크포인트 디렉토리가 비어있으면 빈 리스트를 반환한다."""
        monkeypatch.setattr("server.CHECKPOINT_DIR", str(tmp_path))
        resp = client.get("/api/checkpoints")
        assert resp.json()["checkpoints"] == []


# ─────────────────────────────────────────────
# POST /api/translate
# ─────────────────────────────────────────────

class TestStartTranslation:
    def _upload_epub(self, client, epub_bytes: bytes, filename: str = "test.epub", **form):
        """EPUB 업로드 헬퍼."""
        data = {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-test",
            "endpoint": "",
            "max_words": "800",
            "resume": "false",
        }
        data.update(form)
        return client.post(
            "/api/translate",
            files={"file": (filename, io.BytesIO(epub_bytes), "application/epub+zip")},
            data=data,
        )

    def test_non_epub_file_returns_400(self, client):
        """EPUB이 아닌 파일 → 400."""
        resp = client.post(
            "/api/translate",
            files={"file": ("test.txt", io.BytesIO(b"text content"), "text/plain")},
            data={
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "sk-test",
                "endpoint": "",
                "max_words": "800",
                "resume": "false",
            },
        )
        assert resp.status_code == 400

    def test_no_filename_returns_4xx(self, client):
        """파일명이 없는 경우 → 4xx (FastAPI 유효성 검사 422 또는 서버 로직 400)."""
        resp = client.post(
            "/api/translate",
            files={"file": ("", io.BytesIO(b"data"), "application/epub+zip")},
            data={
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "sk-test",
                "endpoint": "",
                "max_words": "800",
                "resume": "false",
            },
        )
        # 빈 파일명은 FastAPI 레벨(422) 또는 애플리케이션 레벨(400) 양쪽에서 거부됨
        assert resp.status_code in (400, 422)

    def test_oversized_file_returns_413(self, client):
        """50MB 초과 파일 → 413."""
        large_content = b"X" * (50 * 1024 * 1024 + 1)
        resp = client.post(
            "/api/translate",
            files={"file": ("big.epub", io.BytesIO(large_content), "application/epub+zip")},
            data={
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "sk-test",
                "endpoint": "",
                "max_words": "800",
                "resume": "false",
            },
        )
        assert resp.status_code == 413

    def test_unsupported_provider_with_no_model_returns_400(self, client, minimal_epub_bytes):
        """알 수 없는 프로바이더 + 모델 미지정 → LLMClient 예외 → 400."""
        with patch("server.LLMClient") as mock_client_cls:
            mock_client_cls.side_effect = ValueError("지원하지 않는 프로바이더: unknown")
            resp = self._upload_epub(
                client, minimal_epub_bytes,
                provider="unknown", model="",
            )
        # 모델 없으면 DEFAULT_MODELS.get("unknown", "") → "" → 400 먼저 처리
        assert resp.status_code == 400

    def test_valid_epub_with_mocked_pipeline_returns_task_id(self, client, minimal_epub_bytes):
        """유효한 EPUB + mock 파이프라인 → task_id 반환."""
        with patch("server.LLMClient") as mock_llm_cls, \
             patch("server.run_pipeline") as mock_pipeline:
            mock_instance = MagicMock()
            mock_instance.check_connection.return_value = True
            mock_llm_cls.return_value = mock_instance
            mock_pipeline.return_value = None

            resp = self._upload_epub(client, minimal_epub_bytes, provider="openai")

        assert resp.status_code == 200
        body = resp.json()
        assert "task_id" in body
        assert len(body["task_id"]) == 12

    def test_valid_epub_response_contains_filename(self, client, minimal_epub_bytes):
        """응답 JSON에 filename 필드가 포함된다."""
        with patch("server.LLMClient") as mock_llm_cls, \
             patch("server.run_pipeline"):
            mock_instance = MagicMock()
            mock_instance.check_connection.return_value = True
            mock_llm_cls.return_value = mock_instance

            resp = self._upload_epub(
                client, minimal_epub_bytes, filename="mybook.epub", provider="openai"
            )

        assert resp.status_code == 200
        assert resp.json()["filename"] == "mybook.epub"

    def test_valid_epub_response_contains_status(self, client, minimal_epub_bytes):
        """응답 JSON에 status 필드가 포함된다."""
        with patch("server.LLMClient") as mock_llm_cls, \
             patch("server.run_pipeline"):
            mock_instance = MagicMock()
            mock_instance.check_connection.return_value = True
            mock_llm_cls.return_value = mock_instance

            resp = self._upload_epub(client, minimal_epub_bytes, provider="openai")

        assert resp.status_code == 200
        assert "status" in resp.json()

    def test_local_provider_unreachable_returns_503(self, client, minimal_epub_bytes):
        """local 프로바이더이고 서버 연결 실패 → 503."""
        with patch("server.LLMClient") as mock_llm_cls:
            mock_instance = MagicMock()
            mock_instance.check_connection.return_value = False
            mock_llm_cls.return_value = mock_instance

            resp = self._upload_epub(
                client, minimal_epub_bytes,
                provider="local",
                model="mlx-community/Qwen3.5-35B-A3B-4bit",
            )

        assert resp.status_code == 503

    def test_path_traversal_filename_sanitized(self, client, minimal_epub_bytes):
        """경로 탐색 시도(../etc/passwd.epub) → 파일명만 추출해 처리된다."""
        with patch("server.LLMClient") as mock_llm_cls, \
             patch("server.run_pipeline"):
            mock_instance = MagicMock()
            mock_instance.check_connection.return_value = True
            mock_llm_cls.return_value = mock_instance

            resp = self._upload_epub(
                client, minimal_epub_bytes,
                filename="../../../etc/passwd.epub",
                provider="openai",
            )

        # 경로 탐색이 sanitize 되었을 때 task가 등록되어 있어야 함
        if resp.status_code == 200:
            task_id = resp.json()["task_id"]
            task = tm.get_task(task_id)
            assert task is not None
            # input_path에 ".." 이 포함되면 안 됨
            assert ".." not in task.input_path


# ─────────────────────────────────────────────
# POST /api/cancel/{task_id}
# ─────────────────────────────────────────────

class TestCancelTranslation:
    def _create_running_task(self, task_id: str = "testtask01"):
        task = tm.create_task(
            task_id=task_id,
            filename="test.epub",
            input_path="uploads/test.epub",
            output_path="outputs/test_kr.epub",
            checkpoint_path="checkpoints/test.json",
        )
        task.status = TaskStatus.RUNNING
        return task

    def test_cancel_existing_running_task_returns_200(self, client):
        self._create_running_task("testtask01")
        resp = client.post("/api/cancel/testtask01")
        assert resp.status_code == 200

    def test_cancel_returns_cancelling_status(self, client):
        self._create_running_task("testtask02")
        resp = client.post("/api/cancel/testtask02")
        assert resp.json()["status"] == "cancelling"

    def test_cancel_nonexistent_task_returns_404(self, client):
        resp = client.post("/api/cancel/nonexistent999")
        assert resp.status_code == 404

    def test_cancel_completed_task_returns_400(self, client):
        task = tm.create_task(
            task_id="done_task",
            filename="test.epub",
            input_path="uploads/test.epub",
            output_path="outputs/test_kr.epub",
            checkpoint_path="checkpoints/test.json",
        )
        task.status = TaskStatus.COMPLETED
        resp = client.post("/api/cancel/done_task")
        assert resp.status_code == 400

    def test_cancel_pending_task_returns_200(self, client):
        """PENDING 상태도 취소 가능하다."""
        tm.create_task(
            task_id="pending_task",
            filename="test.epub",
            input_path="uploads/test.epub",
            output_path="outputs/test_kr.epub",
            checkpoint_path="checkpoints/test.json",
        )
        # PENDING이 기본값
        resp = client.post("/api/cancel/pending_task")
        assert resp.status_code == 200

    def test_cancel_response_contains_task_id(self, client):
        self._create_running_task("task_with_id")
        resp = client.post("/api/cancel/task_with_id")
        assert resp.json()["task_id"] == "task_with_id"


# ─────────────────────────────────────────────
# GET /api/download/{task_id}
# ─────────────────────────────────────────────

class TestDownloadResult:
    def _create_completed_task(self, task_id: str, output_path: str):
        task = tm.create_task(
            task_id=task_id,
            filename="test.epub",
            input_path="uploads/test.epub",
            output_path=output_path,
            checkpoint_path="checkpoints/test.json",
        )
        task.status = TaskStatus.COMPLETED
        return task

    def test_download_nonexistent_task_returns_404(self, client):
        resp = client.get("/api/download/nonexistent_dl")
        assert resp.status_code == 404

    def test_download_incomplete_task_returns_400(self, client):
        """완료되지 않은 작업 다운로드 → 400."""
        task = tm.create_task(
            task_id="running_dl",
            filename="test.epub",
            input_path="uploads/test.epub",
            output_path="outputs/test_kr.epub",
            checkpoint_path="checkpoints/test.json",
        )
        task.status = TaskStatus.RUNNING
        resp = client.get("/api/download/running_dl")
        assert resp.status_code == 400

    def test_download_completed_but_missing_file_returns_404(self, client):
        """완료 상태이나 출력 파일이 없으면 404."""
        self._create_completed_task("no_file_task", "outputs/nonexistent_output.epub")
        resp = client.get("/api/download/no_file_task")
        assert resp.status_code == 404

    def test_download_completed_with_file_returns_200(self, client, tmp_path):
        """완료 상태 + 실제 파일 존재 → 200 + 파일 내용."""
        # 임시 출력 파일 생성
        out_file = tmp_path / "result_kr.epub"
        out_file.write_bytes(b"fake epub content")

        self._create_completed_task("has_file_task", str(out_file))
        resp = client.get("/api/download/has_file_task")
        assert resp.status_code == 200
        assert resp.content == b"fake epub content"

    def test_download_response_content_type(self, client, tmp_path):
        """다운로드 응답의 Content-Type은 application/epub+zip이다."""
        out_file = tmp_path / "result_kr.epub"
        out_file.write_bytes(b"epub bytes")

        self._create_completed_task("ct_task", str(out_file))
        resp = client.get("/api/download/ct_task")
        assert resp.status_code == 200
        assert "epub" in resp.headers.get("content-type", "").lower()

    def test_download_failed_task_returns_400(self, client):
        """실패 상태 작업 다운로드 → 400."""
        task = tm.create_task(
            task_id="failed_dl",
            filename="test.epub",
            input_path="uploads/test.epub",
            output_path="outputs/test_kr.epub",
            checkpoint_path="checkpoints/test.json",
        )
        task.status = TaskStatus.FAILED
        resp = client.get("/api/download/failed_dl")
        assert resp.status_code == 400
