# Phase 2 코드 리뷰 반영 로그

**작성일:** 2026-03-30
**대상 리뷰:** docs/11-phase2-code-review.md

---

## 수정된 파일

- `server.py` — checkpoint_path에 task_id 추가, cleanup에서 3개 파일 전체 삭제, remove_task() 사용, list_checkpoints to_thread 래핑, check_connection to_thread 래핑
- `task_manager.py` — get_all_tasks() 얕은 복사 반환, remove_task() 함수 추가
- `static/app.js` — SSE error/onerror 핸들러 분리, 네트워크 에러 시 진행 중 번역 유지
- `translate.py` — log_handler를 translate + src 패키지 로거에 모두 등록
- `run.sh` — --host 0.0.0.0 -> 127.0.0.1

---

## 리뷰 반영 내역

### [필수] 5건 — 전부 반영 완료

| # | 항목 | 상태 |
|---|------|------|
| 1 | checkpoint_path에 task_id 포함 | 반영 완료 — `{task_id}_{stem}_progress.json` |
| 2 | cleanup에서 output_path, checkpoint_path 삭제 추가 | 반영 완료 — getattr 루프로 3개 경로 전부 삭제 |
| 3 | get_all_tasks() 캡슐화 + remove_task() 추가 | 반영 완료 — dict(_tasks) 복사본 반환, remove_task() 신규 추가 |
| 4 | list_checkpoints 동기 호출 -> to_thread | 반영 완료 — _load_checkpoints_sync() 분리 후 asyncio.to_thread 래핑 |
| 5 | SSE onerror 핸들링 개선 | 반영 완료 — e.data 유무로 분기, 네트워크 에러는 재연결 카운터에 맡김 |

### [권장] 3건 — 전부 반영 완료

| # | 항목 | 상태 |
|---|------|------|
| 6 | client.check_connection() -> asyncio.to_thread | 반영 완료 |
| 7 | log_handler를 src 패키지 로거에도 추가 | 반영 완료 — translate + src 두 로거에 등록/해제 |
| 8 | run.sh host -> 127.0.0.1 | 반영 완료 |

---

## 설계서 대비 변경점

- task_manager.py의 checkpoint_path 필드는 기존에 이미 존재했으므로 추가 불필요
- translate.py의 log_handler 등록을 logger.addHandler 한 줄에서 for 루프로 변경 (translate, src 두 로거)

---

## 알려진 이슈

- 파일 크기 제한은 여전히 메모리 선적재 방식 (방법 A). 리뷰에서 Phase 2 범위 허용으로 판단됨
- SSE 재연결 시 로그 중복 전송 가능 (log_cursor가 로컬 변수이므로 재연결 시 0으로 리셋). 리뷰에서 인지된 한계

---

## 실행 확인

```
$ python3 -c "import task_manager"  -> OK
$ python3 -c "import server"        -> OK
$ python3 -c "import translate"     -> OK
$ FastAPI routes: /api/translate, /api/progress/{task_id}, /api/cancel/{task_id},
  /api/download/{task_id}, /api/checkpoints, /, /static -> 전부 등록 확인
```
