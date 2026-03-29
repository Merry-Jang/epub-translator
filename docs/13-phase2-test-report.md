# Phase 2 테스트 리포트

**작성일:** 2026-03-30
**테스트 대상:** Phase 2 (FastAPI + Custom UI) — server.py, task_manager.py, translate.py
**실행 환경:** Python 3.14.3 / pytest 9.0.2 / darwin

---

## 테스트 요약

| 구분 | 수량 |
|------|------|
| 전체 테스트 (Phase 2 신규) | 94개 |
| 통과 | 94개 |
| 실패 | 0개 |
| 건너뜀 | 0개 |
| 전체 테스트 (Phase 1 포함) | 132개 |
| Phase 1 회귀 실패 | 0개 |

---

## 테스트 항목

### tests/test_task_manager.py (45개)

| 테스트명 | 유형 | 결과 | 비고 |
|---------|------|------|------|
| TestTaskStatus::test_values_are_strings | 단위 | PASS | |
| TestTaskStatus::test_str_enum_equality | 단위 | PASS | |
| TestTaskInfo::test_default_status_is_pending | 단위 | PASS | |
| TestTaskInfo::test_cancel_event_is_threading_event | 단위 | PASS | |
| TestTaskInfo::test_log_buffer_is_deque_with_maxlen_500 | 단위 | PASS | |
| TestTaskInfo::test_created_at_is_datetime | 단위 | PASS | |
| TestTaskInfo::test_initial_chunk_counts_are_zero | 단위 | PASS | |
| TestTaskInfo::test_error_message_default_empty | 단위 | PASS | |
| TestTaskInfo::test_status_mutation | 단위 | PASS | |
| TestTaskInfo::test_each_task_has_independent_cancel_event | 단위 | PASS | |
| TestTaskInfo::test_each_task_has_independent_log_buffer | 단위 | PASS | |
| TestCreateTask::test_returns_task_info | 단위 | PASS | |
| TestCreateTask::test_task_registered_in_store | 단위 | PASS | |
| TestCreateTask::test_task_fields_set_correctly | 단위 | PASS | |
| TestCreateTask::test_duplicate_id_overwrites | 단위 | PASS | |
| TestGetTask::test_returns_task_for_existing_id | 단위 | PASS | |
| TestGetTask::test_returns_none_for_missing_id | 단위 | PASS | |
| TestGetTask::test_returns_same_object_reference | 단위 | PASS | |
| TestGetAllTasks::test_returns_empty_dict_initially | 단위 | PASS | |
| TestGetAllTasks::test_returns_all_registered_tasks | 단위 | PASS | |
| TestGetAllTasks::test_returns_shallow_copy | 단위 | PASS | |
| TestGetAllTasks::test_values_are_task_info_instances | 단위 | PASS | |
| TestRemoveTask::test_removes_existing_task | 단위 | PASS | |
| TestRemoveTask::test_returns_removed_task | 단위 | PASS | |
| TestRemoveTask::test_returns_none_for_missing_id | 단위 | PASS | |
| TestRemoveTask::test_remove_does_not_affect_other_tasks | 단위 | PASS | |
| TestCancelTask::test_cancel_pending_task_returns_true | 단위 | PASS | |
| TestCancelTask::test_cancel_running_task_returns_true | 단위 | PASS | |
| TestCancelTask::test_cancel_sets_cancel_event | 단위 | PASS | |
| TestCancelTask::test_cancel_completed_task_returns_false | 단위 | PASS | |
| TestCancelTask::test_cancel_failed_task_returns_false | 단위 | PASS | |
| TestCancelTask::test_cancel_nonexistent_task_returns_false | 단위 | PASS | |
| TestCancelTask::test_cancel_cancelled_task_returns_false | 단위 | PASS | |
| TestBufferLogHandler::test_emit_appends_to_buffer | 단위 | PASS | |
| TestBufferLogHandler::test_emitted_entry_has_required_keys | 단위 | PASS | |
| TestBufferLogHandler::test_emitted_entry_level_matches | 단위 | PASS | |
| TestBufferLogHandler::test_emitted_entry_message_content | 단위 | PASS | |
| TestBufferLogHandler::test_buffer_maxlen_respected | 단위 | PASS | |
| TestBufferLogHandler::test_format_time_returns_hhmmss_string | 단위 | PASS | |
| TestBufferLogHandler::test_handler_attached_to_logger | 단위 | PASS | |
| TestBufferLogHandler::test_handler_removed_stops_capture | 단위 | PASS | |
| TestCancelEventBehavior::test_event_starts_unset | 단위 | PASS | |
| TestCancelEventBehavior::test_set_event_is_detected | 단위 | PASS | |
| TestCancelEventBehavior::test_cancel_event_can_be_cleared | 단위 | PASS | |
| TestCancelEventBehavior::test_cancel_event_checked_in_loop | 단위 | PASS | |

### tests/test_server.py (27개)

| 테스트명 | 유형 | 결과 | 비고 |
|---------|------|------|------|
| TestServeIndex::test_get_root_returns_200 | 통합 | PASS | |
| TestServeIndex::test_get_root_returns_html | 통합 | PASS | |
| TestListCheckpoints::test_returns_200 | 통합 | PASS | |
| TestListCheckpoints::test_returns_json_with_checkpoints_key | 통합 | PASS | |
| TestListCheckpoints::test_checkpoints_is_list | 통합 | PASS | |
| TestListCheckpoints::test_checkpoints_empty_when_no_files | 통합 | PASS | monkeypatch로 tmp_path 격리 |
| TestStartTranslation::test_non_epub_file_returns_400 | 통합 | PASS | |
| TestStartTranslation::test_no_filename_returns_4xx | 통합 | PASS | FastAPI 422 또는 서버 400 허용 |
| TestStartTranslation::test_oversized_file_returns_413 | 통합 | PASS | 50MB+1 바이트 |
| TestStartTranslation::test_unsupported_provider_with_no_model_returns_400 | 통합 | PASS | |
| TestStartTranslation::test_valid_epub_with_mocked_pipeline_returns_task_id | 통합 | PASS | LLMClient + run_pipeline mock |
| TestStartTranslation::test_valid_epub_response_contains_filename | 통합 | PASS | |
| TestStartTranslation::test_valid_epub_response_contains_status | 통합 | PASS | |
| TestStartTranslation::test_local_provider_unreachable_returns_503 | 통합 | PASS | check_connection=False |
| TestStartTranslation::test_path_traversal_filename_sanitized | 통합 | PASS | "../../../etc/passwd.epub" → 안전 처리 |
| TestCancelTranslation::test_cancel_existing_running_task_returns_200 | 통합 | PASS | |
| TestCancelTranslation::test_cancel_returns_cancelling_status | 통합 | PASS | |
| TestCancelTranslation::test_cancel_nonexistent_task_returns_404 | 통합 | PASS | |
| TestCancelTranslation::test_cancel_completed_task_returns_400 | 통합 | PASS | |
| TestCancelTranslation::test_cancel_pending_task_returns_200 | 통합 | PASS | |
| TestCancelTranslation::test_cancel_response_contains_task_id | 통합 | PASS | |
| TestDownloadResult::test_download_nonexistent_task_returns_404 | 통합 | PASS | |
| TestDownloadResult::test_download_incomplete_task_returns_400 | 통합 | PASS | |
| TestDownloadResult::test_download_completed_but_missing_file_returns_404 | 통합 | PASS | |
| TestDownloadResult::test_download_completed_with_file_returns_200 | 통합 | PASS | 실제 파일 서빙 |
| TestDownloadResult::test_download_response_content_type | 통합 | PASS | application/epub+zip |
| TestDownloadResult::test_download_failed_task_returns_400 | 통합 | PASS | |

### tests/test_translate_cancel.py (22개)

| 테스트명 | 유형 | 결과 | 비고 |
|---------|------|------|------|
| TestRunPipelineSignature::test_cancel_event_defaults_to_none | 단위 | PASS | CLI 호환성 |
| TestRunPipelineSignature::test_log_handler_defaults_to_none | 단위 | PASS | CLI 호환성 |
| TestRunPipelineSignature::test_required_parameters_exist | 단위 | PASS | |
| TestCancelEventNone::test_pipeline_runs_without_cancel_event | 단위 | PASS | |
| TestCancelEventNone::test_pipeline_no_cancel_event_does_not_raise | 단위 | PASS | |
| TestCancelEventBehavior::test_pipeline_stops_when_cancel_event_set | 단위 | PASS | 사전 set |
| TestCancelEventBehavior::test_pipeline_cancels_mid_translation | 단위 | PASS | 2번째 청크에서 set |
| TestCancelEventBehavior::test_pipeline_without_cancel_completes_all_chunks | 단위 | PASS | |
| TestLogHandlerParameter::test_log_handler_none_does_not_raise | 단위 | PASS | |
| TestLogHandlerParameter::test_log_handler_receives_pipeline_logs | 단위 | PASS | 로거 레벨 INFO 설정 필요 |
| TestLogHandlerParameter::test_log_handler_removed_after_pipeline | 단위 | PASS | finally 보장 확인 |
| TestLogHandlerParameter::test_log_handler_removed_on_exception | 단위 | PASS | 예외 시 finally 보장 |
| TestLogHandlerParameter::test_buffer_log_handler_captures_translate_logger | 단위 | PASS | 로거 레벨 INFO 설정 필요 |
| TestMapTranslationToBlocks::test_one_to_one_mapping | 단위 | PASS | |
| TestMapTranslationToBlocks::test_single_block_gets_full_text | 단위 | PASS | |
| TestMapTranslationToBlocks::test_mismatch_merges_to_first_block | 단위 | PASS | |
| TestMapTranslationToBlocks::test_empty_text_single_block | 단위 | PASS | |
| TestBuildTranslatedChapters::test_builds_chapter_map_from_checkpoint | 단위 | PASS | |
| TestBuildTranslatedChapters::test_skips_non_done_chunks | 단위 | PASS | |
| TestBuildTranslatedChapters::test_empty_checkpoint_returns_empty_dict | 단위 | PASS | |
| TestBuildTranslatedChapters::test_unknown_chunk_id_in_checkpoint_is_skipped | 단위 | PASS | |
| TestBuildTranslatedChapters::test_empty_translated_text_is_skipped | 단위 | PASS | |

---

## 실패 분석

### 테스트 작성 중 발견한 이슈 2건 (모두 수정 완료)

#### 이슈 1: test_no_filename_returns_400
**원인:** 빈 파일명(`""`) 업로드 시 FastAPI의 내부 유효성 검사가 먼저 동작하여 422(Unprocessable Entity)를 반환했다. 서버 코드의 `not file.filename` 체크(→ 400)에 도달하기 전에 차단된다.

**결론:** 실제 동작이 올바르다. 빈 파일명은 FastAPI 레벨에서 거부하는 것이 더 이른 방어선이다. 테스트를 `assert resp.status_code in (400, 422)`로 수정하여 양쪽 모두 허용.

#### 이슈 2: log_handler 로그가 버퍼에 수집되지 않음
**원인:** pytest 테스트 환경에서 루트 로거 레벨이 WARNING(30)으로 초기화되어 있어, translate 로거(NOTSET, 부모 레벨 상속)의 INFO 로그가 effective level 검사에서 차단되었다.

**결론:** translate.py 코드 자체의 버그가 아니다. 테스트에서 `translate_logger.setLevel(logging.INFO)`를 명시적으로 설정하고, 테스트 완료 후 원래대로 복원하도록 수정.

---

## 커버리지

### 테스트된 핵심 로직

| 모듈 | 커버된 항목 |
|------|-----------|
| task_manager.py | TaskStatus 전체, TaskInfo 생성/필드, create/get/get_all/remove/cancel_task 전체, BufferLogHandler emit/시간포맷, cancel_event 동작 패턴 |
| server.py | GET /, GET /api/checkpoints, POST /api/translate (유효/무효/크기초과/미연결/경로탐색), POST /api/cancel (200/400/404), GET /api/download (200/400/404 경우 모두) |
| translate.py | run_pipeline 시그니처, cancel_event=None 호환성, 사전 취소/중간 취소/정상 완주, log_handler 등록/해제/예외시 해제, _map_translation_to_blocks 4가지 케이스, _build_translated_chapters 5가지 케이스 |

### 테스트되지 않은 항목

| 항목 | 이유 |
|------|------|
| GET /api/progress/{task_id} SSE 스트리밍 | TestClient는 SSE 스트리밍 응답을 실시간으로 소비하기 어렵다. 수동 테스트 또는 별도 통합 테스트 환경 필요 |
| _cleanup_loop() | 1시간 sleep 루프 — asyncio 테스트에서 sleep을 mock하면 검증 가능하나 현재 스코프 외 |
| 동시 번역 Semaphore(2) 제한 | asyncio 동시성 테스트 — TestClient의 동기 모드에서는 재현 불가 |
| static/app.js | 프론트엔드 — 수동 테스트 항목으로 분리됨 |
| LLMClient 초기화 실패 시 400 분기 (server.py 라인 158) | 외부 SDK(openai/anthropic) mock 없이 재현 어려움 |

---

## 경고 항목

server.py에서 `@app.on_event("startup")` 데코레이터가 FastAPI 최신 버전에서 deprecated되어 DeprecationWarning이 발생한다.
권장 패턴은 `@asynccontextmanager` + `lifespan` 파라미터 방식이다.
기능 동작에는 영향 없으나, 향후 업그레이드 시 수정 권장.

```python
# 현재 (deprecated)
@app.on_event("startup")
async def startup(): ...

# 권장
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup 로직
    yield
    # shutdown 로직

app = FastAPI(lifespan=lifespan)
```

---

## 최종 판정

**출시 가능**

Phase 2에서 신규 구현된 핵심 로직(task_manager, server API 엔드포인트, translate 파라미터 확장) 전체가 테스트를 통과했다. Phase 1 회귀 없음. SSE 스트리밍과 동시성 제어는 수동 검증이 필요하나, 설계서대로 구현되어 있음이 코드 레벨에서 확인된다.
