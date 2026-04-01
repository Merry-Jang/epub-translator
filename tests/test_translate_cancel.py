"""translate.py 단위 테스트 — cancel_event, log_handler, CLI 호환성."""

import logging
import threading
from collections import deque
from unittest.mock import MagicMock, call, patch

import pytest

from task_manager import BufferLogHandler


# ─────────────────────────────────────────────
# Helpers / Fixtures
# ─────────────────────────────────────────────

def make_mock_client() -> MagicMock:
    """LLMClient mock 객체를 생성한다."""
    client = MagicMock()
    client.provider = "openai"
    return client


def make_mock_chunk(chunk_id: str = "ch01_chunk00", chapter_id: str = "ch01") -> MagicMock:
    """Chunk mock 객체를 생성한다."""
    chunk = MagicMock()
    chunk.id = chunk_id
    chunk.chapter_id = chapter_id
    chunk.text = "Hello world."
    chunk.context = ""
    chunk.block_indices = [0]
    return chunk


def make_mock_chapter(chapter_id: str = "ch01") -> MagicMock:
    """Chapter mock 객체를 생성한다."""
    chapter = MagicMock()
    chapter.id = chapter_id
    chapter.title = "Chapter 1"
    chapter.text_blocks = [MagicMock()]
    return chapter


# ─────────────────────────────────────────────
# run_pipeline 시그니처 / CLI 호환성
# ─────────────────────────────────────────────

class TestRunPipelineSignature:
    def test_cancel_event_defaults_to_none(self):
        """run_pipeline의 cancel_event 파라미터 기본값이 None이다."""
        import inspect
        from translate import run_pipeline
        sig = inspect.signature(run_pipeline)
        assert sig.parameters["cancel_event"].default is None

    def test_log_handler_defaults_to_none(self):
        """run_pipeline의 log_handler 파라미터 기본값이 None이다."""
        import inspect
        from translate import run_pipeline
        sig = inspect.signature(run_pipeline)
        assert sig.parameters["log_handler"].default is None

    def test_required_parameters_exist(self):
        """run_pipeline에 필수 파라미터 6개가 모두 존재한다."""
        import inspect
        from translate import run_pipeline
        sig = inspect.signature(run_pipeline)
        required = {
            name for name, p in sig.parameters.items()
            if p.default is inspect.Parameter.empty
        }
        assert "input_path" in required
        assert "output_path" in required
        assert "model" in required
        assert "checkpoint_path" in required
        assert "resume" in required
        assert "max_words" in required
        assert "client" in required


# ─────────────────────────────────────────────
# cancel_event=None 일 때 정상 동작 (CLI 호환성)
# ─────────────────────────────────────────────

class TestCancelEventNone:
    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_pipeline_runs_without_cancel_event(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """cancel_event=None이면 파이프라인이 정상 완주한다."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        chunk = make_mock_chunk()

        mock_parse.return_value = [chapter]
        mock_chunk.return_value = [chunk]
        mock_load.return_value = None  # 새 체크포인트 시작
        mock_translate.return_value = "안녕 세계."
        mock_save.return_value = None
        mock_build.return_value = None

        client = make_mock_client()
        out = str(tmp_path / "out_kr.epub")
        ckpt = str(tmp_path / "ckpt.json")

        # cancel_event 미전달 → 기본값 None
        run_pipeline(
            input_path="test.epub",
            output_path=out,
            model="gpt-4o-mini",
            checkpoint_path=ckpt,
            resume=False,
            max_words=800,
            client=client,
        )

        # translate_chunk가 호출됐으면 파이프라인이 정상 완주한 것
        mock_translate.assert_called_once()
        mock_build.assert_called_once()

    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_pipeline_no_cancel_event_does_not_raise(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """cancel_event=None이면 AttributeError 등 예외가 발생하지 않는다."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        chunk = make_mock_chunk()
        mock_parse.return_value = [chapter]
        mock_chunk.return_value = [chunk]
        mock_load.return_value = None
        mock_translate.return_value = "한국어 번역"
        mock_save.return_value = None
        mock_build.return_value = None

        client = make_mock_client()

        # 예외 없이 실행되어야 함
        run_pipeline(
            input_path="test.epub",
            output_path=str(tmp_path / "out.epub"),
            model="gpt-4o-mini",
            checkpoint_path=str(tmp_path / "ck.json"),
            resume=False,
            max_words=800,
            client=client,
            cancel_event=None,
        )


# ─────────────────────────────────────────────
# cancel_event 설정 시 번역 중단
# ─────────────────────────────────────────────

class TestCancelEventBehavior:
    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_pipeline_stops_when_cancel_event_set(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """cancel_event가 미리 set된 경우 번역 루프 진입 전 중단된다."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        chunks = [make_mock_chunk(f"ch01_chunk{i:02d}") for i in range(5)]
        mock_parse.return_value = [chapter]
        mock_chunk.return_value = chunks
        mock_load.return_value = None
        mock_translate.return_value = "번역"
        mock_save.return_value = None
        mock_build.return_value = None

        cancel_event = threading.Event()
        cancel_event.set()  # 시작 전에 취소

        run_pipeline(
            input_path="test.epub",
            output_path=str(tmp_path / "out.epub"),
            model="gpt-4o-mini",
            checkpoint_path=str(tmp_path / "ck.json"),
            resume=False,
            max_words=800,
            client=make_mock_client(),
            cancel_event=cancel_event,
        )

        # 취소 신호가 있으므로 translate_chunk는 호출되지 않아야 함
        mock_translate.assert_not_called()
        # build_epub도 호출되지 않아야 함
        mock_build.assert_not_called()

    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_pipeline_cancels_mid_translation(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """번역 중 cancel_event가 set되면 이후 청크를 처리하지 않는다."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        # 3개 청크 생성
        chunks = [make_mock_chunk(f"ch01_chunk{i:02d}") for i in range(3)]
        mock_parse.return_value = [chapter]
        mock_chunk.return_value = chunks
        mock_load.return_value = None
        mock_save.return_value = None
        mock_build.return_value = None

        cancel_event = threading.Event()
        call_count = [0]

        def translate_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] >= 2:
                cancel_event.set()  # 두 번째 청크 번역 후 취소
            return "번역 결과"

        mock_translate.side_effect = translate_side_effect

        run_pipeline(
            input_path="test.epub",
            output_path=str(tmp_path / "out.epub"),
            model="gpt-4o-mini",
            checkpoint_path=str(tmp_path / "ck.json"),
            resume=False,
            max_words=800,
            client=make_mock_client(),
            cancel_event=cancel_event,
        )

        # 3개 중 최대 2개까지만 처리됨
        assert mock_translate.call_count <= 2
        # build_epub은 취소 후 스킵
        mock_build.assert_not_called()

    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_pipeline_without_cancel_completes_all_chunks(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """cancel_event를 설정하지 않으면 모든 청크가 번역된다."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        chunks = [make_mock_chunk(f"ch01_chunk{i:02d}") for i in range(3)]
        mock_parse.return_value = [chapter]
        mock_chunk.return_value = chunks
        mock_load.return_value = None
        mock_translate.return_value = "번역 완료"
        mock_save.return_value = None
        mock_build.return_value = None

        run_pipeline(
            input_path="test.epub",
            output_path=str(tmp_path / "out.epub"),
            model="gpt-4o-mini",
            checkpoint_path=str(tmp_path / "ck.json"),
            resume=False,
            max_words=800,
            client=make_mock_client(),
        )

        # 모든 청크 번역 완료
        assert mock_translate.call_count == 3
        mock_build.assert_called_once()


# ─────────────────────────────────────────────
# log_handler 파라미터 동작
# ─────────────────────────────────────────────

class TestLogHandlerParameter:
    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_log_handler_none_does_not_raise(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """log_handler=None이면 예외 없이 실행된다."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        chunk = make_mock_chunk()
        mock_parse.return_value = [chapter]
        mock_chunk.return_value = [chunk]
        mock_load.return_value = None
        mock_translate.return_value = "번역"
        mock_save.return_value = None
        mock_build.return_value = None

        run_pipeline(
            input_path="test.epub",
            output_path=str(tmp_path / "out.epub"),
            model="gpt-4o-mini",
            checkpoint_path=str(tmp_path / "ck.json"),
            resume=False,
            max_words=800,
            client=make_mock_client(),
            log_handler=None,
        )

    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_log_handler_receives_pipeline_logs(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """log_handler가 전달되면 파이프라인 로그가 핸들러에 전달된다."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        chunk = make_mock_chunk()
        mock_parse.return_value = [chapter]
        mock_chunk.return_value = [chunk]
        mock_load.return_value = None
        mock_translate.return_value = "번역"
        mock_save.return_value = None
        mock_build.return_value = None

        buf = deque(maxlen=500)
        handler = BufferLogHandler(buf)

        # translate 로거가 INFO를 처리하도록 레벨 설정
        # (테스트 환경에서는 루트 로거가 WARNING으로 초기화되어 있어 INFO가 차단됨)
        translate_logger = logging.getLogger("translate")
        original_level = translate_logger.level
        translate_logger.setLevel(logging.INFO)
        try:
            run_pipeline(
                input_path="test.epub",
                output_path=str(tmp_path / "out.epub"),
                model="gpt-4o-mini",
                checkpoint_path=str(tmp_path / "ck.json"),
                resume=False,
                max_words=800,
                client=make_mock_client(),
                log_handler=handler,
            )
        finally:
            translate_logger.setLevel(original_level)

        # 파이프라인에서 최소 1개 이상 로그가 발생해야 함
        assert len(buf) > 0

    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_log_handler_removed_after_pipeline(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """파이프라인 완료 후 log_handler가 translate 로거에서 제거된다."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        chunk = make_mock_chunk()
        mock_parse.return_value = [chapter]
        mock_chunk.return_value = [chunk]
        mock_load.return_value = None
        mock_translate.return_value = "번역"
        mock_save.return_value = None
        mock_build.return_value = None

        buf = deque(maxlen=500)
        handler = BufferLogHandler(buf)

        run_pipeline(
            input_path="test.epub",
            output_path=str(tmp_path / "out.epub"),
            model="gpt-4o-mini",
            checkpoint_path=str(tmp_path / "ck.json"),
            resume=False,
            max_words=800,
            client=make_mock_client(),
            log_handler=handler,
        )

        translate_logger = logging.getLogger("translate")
        assert handler not in translate_logger.handlers

    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_log_handler_removed_on_exception(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """파이프라인에서 예외 발생 시에도 log_handler가 제거된다 (finally 보장)."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        chunk = make_mock_chunk()
        mock_parse.return_value = [chapter]
        mock_chunk.return_value = [chunk]
        mock_load.return_value = None
        mock_translate.side_effect = RuntimeError("unexpected error")
        mock_save.return_value = None
        mock_build.return_value = None

        buf = deque(maxlen=500)
        handler = BufferLogHandler(buf)

        with pytest.raises(RuntimeError):
            run_pipeline(
                input_path="test.epub",
                output_path=str(tmp_path / "out.epub"),
                model="gpt-4o-mini",
                checkpoint_path=str(tmp_path / "ck.json"),
                resume=False,
                max_words=800,
                client=make_mock_client(),
                log_handler=handler,
            )

        translate_logger = logging.getLogger("translate")
        assert handler not in translate_logger.handlers

    @patch("translate.build_epub")
    @patch("translate.save_progress")
    @patch("translate.load_progress")
    @patch("translate.translate_chunk")
    @patch("translate.chunk_chapter")
    @patch("translate.parse_epub")
    def test_buffer_log_handler_captures_translate_logger(
        self,
        mock_parse, mock_chunk, mock_translate,
        mock_load, mock_save, mock_build,
        tmp_path,
    ):
        """BufferLogHandler가 translate 모듈 로거의 INFO 이상을 캡처한다."""
        from translate import run_pipeline

        chapter = make_mock_chapter()
        chunk = make_mock_chunk()
        mock_parse.return_value = [chapter]
        mock_chunk.return_value = [chunk]
        mock_load.return_value = None
        mock_translate.return_value = "번역"
        mock_save.return_value = None
        mock_build.return_value = None

        buf = deque(maxlen=500)
        handler = BufferLogHandler(buf)

        # 테스트 환경에서 루트 로거 레벨이 WARNING이므로 translate 로거에 INFO 레벨 지정
        translate_logger = logging.getLogger("translate")
        original_level = translate_logger.level
        translate_logger.setLevel(logging.INFO)
        try:
            run_pipeline(
                input_path="test.epub",
                output_path=str(tmp_path / "out.epub"),
                model="gpt-4o-mini",
                checkpoint_path=str(tmp_path / "ck.json"),
                resume=False,
                max_words=800,
                client=make_mock_client(),
                log_handler=handler,
            )
        finally:
            translate_logger.setLevel(original_level)

        messages = [e["message"] for e in buf]
        # EPUB 파싱 시작 메시지가 캡처되어야 함
        assert any("파싱" in m or "챕터" in m or "청크" in m for m in messages)


# ─────────────────────────────────────────────
# _map_translation_to_blocks 단위 테스트
# ─────────────────────────────────────────────

class TestMapTranslationToBlocks:
    def test_one_to_one_mapping(self):
        """블록 수와 분할 수가 같으면 1:1 매핑된다."""
        from translate import _map_translation_to_blocks

        chunk = MagicMock()
        chunk.id = "ch01_chunk00"
        chunk.block_indices = [0, 1, 2]

        result = _map_translation_to_blocks("가나다\n\n라마바\n\n사아자", chunk)
        assert result == {0: "가나다", 1: "라마바", 2: "사아자"}

    def test_single_block_gets_full_text(self):
        """블록이 1개이면 전체 번역 텍스트가 할당된다."""
        from translate import _map_translation_to_blocks

        chunk = MagicMock()
        chunk.id = "ch01_chunk00"
        chunk.block_indices = [0]

        result = _map_translation_to_blocks("가나다\n\n라마바", chunk)
        assert result == {0: "가나다\n\n라마바"}

    def test_mismatch_merges_to_first_block(self):
        """블록 수와 분할 수가 다르면 전체를 첫 블록에 합친다."""
        from translate import _map_translation_to_blocks

        chunk = MagicMock()
        chunk.id = "ch01_chunk00"
        chunk.block_indices = [0, 1, 2]

        # 2개만 번역됨
        result = _map_translation_to_blocks("가나다\n\n라마바", chunk)
        assert result[0] == "가나다\n\n라마바"
        assert result[1] == ""
        assert result[2] == ""

    def test_empty_text_single_block(self):
        """빈 문자열 + 블록 1개 → 빈 문자열 할당."""
        from translate import _map_translation_to_blocks

        chunk = MagicMock()
        chunk.id = "ch01_chunk00"
        chunk.block_indices = [5]

        result = _map_translation_to_blocks("", chunk)
        assert result == {5: ""}


# ─────────────────────────────────────────────
# _build_translated_chapters 단위 테스트
# ─────────────────────────────────────────────

class TestBuildTranslatedChapters:
    def test_builds_chapter_map_from_checkpoint(self):
        """체크포인트 'done' 청크를 올바른 챕터 구조로 조립한다."""
        from translate import _build_translated_chapters

        chunk = make_mock_chunk("ch01_chunk00", "ch01")

        checkpoint_data = {
            "chunks": {
                "ch01_chunk00": {
                    "status": "done",
                    "translated": "안녕 세계.",
                    "block_indices": [0],
                }
            }
        }

        result = _build_translated_chapters(checkpoint_data, [chunk])
        assert "ch01" in result
        assert 0 in result["ch01"]
        assert result["ch01"][0] == "안녕 세계."

    def test_skips_non_done_chunks(self):
        """'done'이 아닌 청크(pending, failed)는 건너뛴다."""
        from translate import _build_translated_chapters

        chunk = make_mock_chunk("ch01_chunk00", "ch01")

        checkpoint_data = {
            "chunks": {
                "ch01_chunk00": {
                    "status": "failed",
                    "translated": "",
                    "block_indices": [0],
                }
            }
        }

        result = _build_translated_chapters(checkpoint_data, [chunk])
        assert result == {}

    def test_empty_checkpoint_returns_empty_dict(self):
        """빈 체크포인트 → 빈 딕셔너리."""
        from translate import _build_translated_chapters

        result = _build_translated_chapters({"chunks": {}}, [])
        assert result == {}

    def test_unknown_chunk_id_in_checkpoint_is_skipped(self):
        """체크포인트에 있지만 all_chunks에 없는 chunk_id는 무시한다."""
        from translate import _build_translated_chapters

        checkpoint_data = {
            "chunks": {
                "unknown_chunk_id": {
                    "status": "done",
                    "translated": "번역",
                    "block_indices": [0],
                }
            }
        }

        result = _build_translated_chapters(checkpoint_data, [])
        assert result == {}

    def test_empty_translated_text_is_skipped(self):
        """번역 텍스트가 비어있는 'done' 청크는 무시한다."""
        from translate import _build_translated_chapters

        chunk = make_mock_chunk("ch01_chunk00", "ch01")

        checkpoint_data = {
            "chunks": {
                "ch01_chunk00": {
                    "status": "done",
                    "translated": "",
                    "block_indices": [0],
                }
            }
        }

        result = _build_translated_chapters(checkpoint_data, [chunk])
        assert result == {}
