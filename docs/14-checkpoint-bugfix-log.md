# Checkpoint Bugfix Log

**수정일:** 2026-03-30

---

## 수정된 파일

| 파일 | 변경 내용 |
|------|----------|
| `server.py` | checkpoint_path에서 task_id 제거, `/api/resume` + `DELETE /api/checkpoint/{filename}` 추가, `_load_checkpoints_sync` 응답에 `checkpoint_file`/`source` 필드 추가 |
| `static/app.js` | `api.resumeTranslation()` + `api.deleteCheckpoint()` 추가, 체크포인트 카드에 이어하기/삭제 버튼 + 이벤트 핸들러 구현 |

## 수정한 버그 3가지

### 1. checkpoint_path에서 task_id 제거 (핵심 버그)
- **Before:** `f"{task_id}_{stem}_progress.json"` -- 매번 새 task_id로 새 체크포인트 경로 생성
- **After:** `f"{stem}_progress.json"` -- 같은 EPUB 파일명이면 같은 체크포인트를 사용
- **효과:** 같은 파일을 다시 업로드하면 기존 체크포인트를 자동으로 이어받음

### 2. 체크포인트에서 이어하기 (`POST /api/resume`)
- 체크포인트 파일명을 받아 source 경로 확인
- source 파일이 없으면 400 에러 (재업로드 안내)
- source 파일이 있으면 resume=True로 번역 시작
- 프론트에서 이어하기 버튼 클릭 -> `/api/resume` 호출 -> SSE 연결

### 3. 체크포인트 삭제 (`DELETE /api/checkpoint/{filename}`)
- 경로 순회 방지 (Path.name으로 파일명만 추출)
- 삭제 후 프론트에서 목록 자동 새로고침

## 보안 고려사항
- `/api/resume`, `/api/checkpoint/{filename}` 모두 `Path(filename).name`으로 경로 순회 공격 방지
- 체크포인트 파일은 CHECKPOINT_DIR 내에서만 조회/삭제 가능

## 미수정 파일
- `src/` 디렉토리: 수정하지 않음 (지시사항 준수)
- `translate.py`: 수정하지 않음 (지시사항 준수)
- `task_manager.py`: 변경 불필요
- `static/index.html`: DOM 변경 불필요 (app.js에서 동적 생성)

## 실행 확인
- `python -c "import server"` -- import OK
- FastAPI 라우트 등록 확인: `/api/resume`, `/api/checkpoint/{filename}` 포함 전체 8개 엔드포인트 정상
