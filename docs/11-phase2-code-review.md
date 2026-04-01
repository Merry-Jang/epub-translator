# 코드 리뷰 — Phase 2 구현 (EPUB Translator Studio)

**작성일:** 2026-03-30
**리뷰어:** Sonnet 4.6 + Gemini 2.5 Flash (교차 리뷰)
**대상:** server.py, task_manager.py, static/index.html, static/app.js, translate.py, run.sh, requirements.txt
**참조:** docs/08-phase2-design.md, docs/09-phase2-design-review.md

---

## 평가 요약

**수정 필요**

설계 리뷰에서 요구한 필수 5개 항목 중 3개(Path Traversal, SSE 블로킹, 세마포어)는 올바르게 구현됐다. 그러나 2개(파일 크기 제한 방식, Task 정리 불완전)는 부분 구현에 그쳤으며, 새로운 버그 2건(cleanup에서 _tasks 직접 pop, list_checkpoints 동기 I/O)이 추가로 발견됐다. XSS 방어는 모범적이다.

---

## 파일별 리뷰

### server.py

**[L57] 버그: `_translation_semaphore` None 가능성**

```python
_translation_semaphore: asyncio.Semaphore | None = None

async def _run_in_background():
    async with _translation_semaphore:  # startup 전에 호출되면 TypeError
```

`startup()` 완료 전에 `POST /api/translate`가 호출되는 엣지 케이스(프로세스 시작 직후 요청)에서 `_translation_semaphore`가 `None`이어서 `TypeError`가 발생한다. `startup` 이벤트 완료 보장은 uvicorn이 하지만, 방어 코드를 추가하는 것이 안전하다.

```python
# 수정: 모듈 레벨에서 즉시 초기화
_translation_semaphore = asyncio.Semaphore(MAX_CONCURRENT)  # startup에서 덮어쓰기 대신
```

또는 `_run_in_background` 내에서 assert로 방어한다.

---

**[L84] 설계 리뷰 미반영: 파일 크기 제한이 메모리 선 적재 방식**

설계 리뷰 [필수 #2]는 방법 A(현재 방식 + 크기 체크)도 수용 가능하다고 했으나, Gemini가 DoS 벡터로 별도 지적했다. 파일을 전부 메모리에 읽은 후 거부하는 방식이므로, MAX_FILE_SIZE 이하지만 큰 파일을 다수 동시 업로드 시 메모리 소진이 가능하다. Phase 2 범위에서는 허용 가능하지만 알려진 한계로 문서화해야 한다.

```python
# 현재
content = await file.read()
if len(content) > MAX_FILE_SIZE:
    raise HTTPException(413, ...)
```

---

**[L84] 버그: 413 발생 시 input_path 파일이 생성되지 않아 `_cleanup_loop`에서 `input_path` 없는 task가 정리됨**

파일 크기 초과 시 `HTTPException`을 던지기 전에 파일을 저장하지 않는 것은 맞다. 그러나 `create_task()`는 그 전 단계(L93: `with open` 이후)에서 호출된다. 코드를 보면 실제로 파일 저장(L86-L88) 후 `create_task()`(L93)가 호출되므로 순서는 맞다. 단, 413 예외가 발생하면 task가 생성되지 않으므로 정리 대상이 되지 않는다. 현재 코드 순서상 문제 없음 — 확인 완료.

---

**[L77-L95] 버그: `_cleanup_loop`에서 `get_all_tasks()` 반환값 직접 `pop` — 설계 불일치**

```python
tasks = get_all_tasks()           # _tasks dict 참조 반환
for task_id in to_remove:
    task = tasks.pop(task_id, None)  # _tasks를 직접 수정
```

`get_all_tasks()`가 `_tasks` 딕셔너리의 **참조**를 반환하므로 `pop` 호출이 실제로 `_tasks`를 수정한다. 그 자체는 의도한 동작이지만 `task_manager.py`의 `get_all_tasks()`가 반환 타입을 `dict[str, TaskInfo]`로 선언한 것과 달리 설계서에는 `list[TaskInfo]` 반환으로 명시되어 있어 설계 불일치다. 또한 cleanup 루프와 요청 처리 코루틴이 동시에 `_tasks`에 접근하는 경쟁 조건이 발생 가능하다(하단 경쟁 조건 섹션 참조).

---

**[L159] 버그: `client.check_connection()`이 async 컨텍스트에서 동기 호출로 이벤트 루프 블로킹**

```python
if provider == "local" and not client.check_connection():
```

`check_connection()`은 `httpx.get()`을 동기 호출하므로 이벤트 루프를 블로킹한다. 타임아웃이 5초이므로 파일 업로드 요청이 몰리면 전체 서버가 5초씩 멈출 수 있다.

```python
# 수정
if provider == "local":
    ok = await asyncio.to_thread(client.check_connection)
    if not ok:
        ...
```

---

**[L256] 버그: `list_checkpoints`에서 `glob` + `load_progress` 동기 I/O가 이벤트 루프 블로킹**

```python
files = glob_mod.glob(os.path.join(CHECKPOINT_DIR, "*_progress.json"))
...
ckpt = load_progress(f)  # 동기 파일 I/O
```

`event_generator`와 동일한 문제다. 체크포인트가 많을수록 전체 파일 목록 읽기 지연이 이벤트 루프에 직접 영향을 미친다.

```python
# 수정
files = await asyncio.to_thread(glob_mod.glob, os.path.join(CHECKPOINT_DIR, "*_progress.json"))
...
ckpt = await asyncio.to_thread(load_progress, f)
```

---

**[L85-L91] 설계 리뷰 미반영: cleanup에서 output_path, checkpoint_path 삭제 누락**

```python
# 현재: input_path만 삭제
if os.path.exists(task.input_path):
    os.unlink(task.input_path)
# output_path, checkpoint_path는 삭제 안 함
```

outputs/, checkpoints/ 디렉토리에 파일이 무기한 누적된다. 설계 리뷰 [필수 #5]의 의도는 모든 임시 파일 정리였다.

```python
# 수정: 세 파일 모두 정리
for path_attr in ('input_path', 'output_path', 'checkpoint_path'):
    path = getattr(task, path_attr)
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError as e:
            logger.warning("파일 삭제 실패: %s — %s", path, e)
```

단, `output_path`는 사용자가 다운로드 전에 삭제될 수 있으므로 24시간 타임아웃이 충분한지 운영 정책을 명시해야 한다.

---

**[L125] 잠재적 버그: `checkpoint_path`에 `task_id`가 없어 동일 파일명 업로드 시 충돌**

```python
checkpoint_path = os.path.join(CHECKPOINT_DIR, f"{stem}_progress.json")
```

`output_path`와 `input_path`에는 `task_id`가 포함되지만(권장 #7 반영), `checkpoint_path`에는 없다. 동일한 책 파일을 동시에 두 번 번역 요청 시 두 작업이 같은 체크포인트 파일을 읽고 쓰는 충돌이 발생한다. 한 작업이 체크포인트를 초기화하면 다른 작업의 진행 상황이 사라진다.

```python
# 수정
checkpoint_path = os.path.join(CHECKPOINT_DIR, f"{task_id}_{stem}_progress.json")
```

---

**[L169-L172] 설계 비준수: `provider` 입력값 enum 검증 없음 (선택 #10 미반영)**

설계 리뷰에서는 [선택] 항목이었으나, 현재 코드에서 지원하지 않는 provider가 들어오면 L218 `DEFAULT_MODELS.get(provider, "")` 에서 빈 문자열이 되어 L144-L147 블록에서 처리된다. 에러는 잡히지만 메시지가 `"지원하지 않는 프로바이더: {provider}"` — 사용자 입력값이 에러 메시지에 그대로 노출되는 정보 유출이 있다. `provider` 값을 허용 목록으로 제한하는 것이 더 안전하다.

---

### task_manager.py

**[L89-L91] 설계 불일치: `get_all_tasks()` 반환 타입이 설계서와 다름**

설계서(`08-phase2-design.md` L191): `get_all_tasks() → list[TaskInfo]` (정렬된 리스트 반환)

실제 구현: `dict[str, TaskInfo]` 반환 (정렬 없음, `_tasks` 참조)

`server.py`의 `_cleanup_loop`이 `.items()`, `.pop()`을 호출하므로 dict로 반환하는 것이 맞지만, 설계서와의 불일치 및 `_tasks` 참조 노출이 의도치 않은 외부 수정을 허용한다.

```python
# 개선: 참조 대신 복사본 반환 + cleanup은 별도 함수로 캡슐화
def get_all_tasks() -> dict[str, TaskInfo]:
    return dict(_tasks)  # 얕은 복사

def remove_task(task_id: str) -> TaskInfo | None:
    return _tasks.pop(task_id, None)
```

---

**[L97] 설계 불일치: `cancel_task()`가 PENDING 상태도 처리하는 것은 올바르나 설계서와 차이**

설계서 L245: `if task and task.status == TaskStatus.RUNNING:` (RUNNING만)

실제 구현: `if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):`

PENDING 상태 취소도 올바른 동작이나 의도적인 변경이면 설계서에 반영해야 한다.

---

**[L186] 설계 불일치: `log_cursor` 필드 누락**

설계서 `TaskInfo`에는 `log_cursor: dict = field(default_factory=dict)` 필드가 명시되어 있으나, 실제 구현에서 제거됐다. `event_generator`에서 로컬 변수 `log_cursor`로 대체했으므로 기능상 문제는 없지만, 재연결 시 커서 상태를 잃는다(아래 SSE 섹션 참조).

---

### static/app.js

**[L144-L152] 설계 리뷰 반영 확인: 재연결 5회 제한 구현됨**

설계 리뷰 [선택 #11]에서 요구한 5회 재연결 실패 카운터가 구현됐다.

```javascript
es.onerror = () => {
    reconnectCount++;
    if (reconnectCount > 5) {
        es.close();
        state.eventSource = null;
        ui.showError('서버 연결이 불안정합니다. 페이지를 새로고침하세요.');
        ui.setStatus('failed');
    }
};
```

단, `reconnectCount` 변수가 `sse.connect()` 함수 내 클로저로 선언되어 있어 재연결 시 리셋되지만, EventSource가 자동 재연결 자체를 새 인스턴스로 수행하지 않고 기존 인스턴스가 재시도하므로 카운터 로직이 실제로 의도대로 동작하는지 검증이 필요하다.

---

**[L132-L141] 버그 가능성: SSE `error` 이벤트 핸들러와 `onerror` 핸들러 혼동**

```javascript
es.addEventListener('error', (e) => {
    // 서버에서 보낸 error 이벤트
    if (e.data) {
        const data = JSON.parse(e.data);
        ...
    }
    ui.setStatus('failed');
    es.close();
    ...
});

es.onerror = () => { ... };  // 네트워크 에러
```

`EventSource`의 `error` 이벤트는 두 가지로 발생한다:
1. 서버에서 `event: error\ndata: {...}` 전송 시 — `e.data` 있음
2. 네트워크 연결 끊김 — `e.data` 없음, `e.type === 'error'`

현재 코드는 2번의 경우도 `es.addEventListener('error')` 핸들러로 진입해 `ui.setStatus('failed')` + `es.close()`를 실행한다. `onerror`는 호출되지 않는다. 즉, 일시적인 네트워크 단절에서도 SSE를 닫아버리는 문제가 있다.

```javascript
// 수정: data 유무로 분기
es.addEventListener('error', (e) => {
    if (e.data) {
        // 서버 발송 error 이벤트
        const data = JSON.parse(e.data);
        ui.showError(data.error || '알 수 없는 오류가 발생했습니다.');
        ui.setStatus('failed');
        es.close();
        state.eventSource = null;
    }
    // data 없는 경우는 onerror에서 처리 (재연결 카운터)
});
```

---

**[L169] 잠재적 XSS: `progressDetail.innerHTML` 에 서버 데이터 삽입**

```javascript
dom.progressDetail.innerHTML =
    `처리 중인 청크: <span class="text-primary font-bold">#${data.completed} / #${data.total}</span>`;
```

`data.completed`와 `data.total`은 서버에서 받은 숫자값이다. JSON 파싱 후 number 타입이면 XSS 위험 없음. 그러나 서버가 비정상 응답을 보내거나 중간자 공격이 발생한 경우를 방어하려면 숫자 타입임을 명시적으로 확인해야 한다.

```javascript
// 방어적 처리
const completed = Number(data.completed) || 0;
const total = Number(data.total) || 0;
dom.progressDetail.innerHTML =
    `처리 중인 청크: <span class="text-primary font-bold">#${completed} / #${total}</span>`;
```

---

**[L256] 체크포인트 렌더링에서 `innerHTML`에 `_escapeHtml` 미적용 항목 확인**

```javascript
`<div class="h-full bg-primary/60" style="width:${pct}%"></div>`
```

`pct`는 `Math.round(...)` 결과로 number이므로 문제없다. `cp.filename`에는 `_escapeHtml` 적용됨(L197). 전반적으로 innerHTML 주입 처리가 양호하다.

---

**[L388] 버그 가능성: SSE 재연결 후 로그 중복**

SSE 연결이 끊기고 재연결되면 서버에서 새 `event_generator` 코루틴이 시작되며 `log_cursor = 0`으로 초기화된다. `log_buffer`에 이미 쌓인 로그 전체를 다시 전송한다. 클라이언트가 화면에 중복 로그 항목을 표시하게 된다. 설계서에 있던 `log_cursor: dict` 필드를 제거한 결과로, 재연결 시 커서 복원 방법이 없다.

단기 해결책: SSE `progress` 이벤트에 `log_cursor` 위치를 포함해 재연결 시 쿼리 파라미터로 전달하거나, 클라이언트에서 이미 수신한 로그를 dedup 처리한다.

---

**[L382] 개선: `resume` 값이 `"true"/"false"` 문자열로 전송됨**

```javascript
formData.append('resume', dom.resumeCheck.checked);
// → "true" 또는 "false" 문자열로 전송
```

FastAPI의 `resume: bool = Form(False)`는 문자열 `"true"/"false"` 파싱을 지원하므로 현재는 동작하지만, `"True"`, `"1"`, `"yes"` 등을 보내면 `False`로 해석될 수 있다. 명시적으로 처리하는 것이 안전하다.

---

### translate.py

**[L113-L114] 설계 준수 확인: `cancel_event`, `log_handler` 파라미터 추가 확인됨**

```python
def run_pipeline(
    ...
    cancel_event: threading.Event | None = None,
    log_handler: logging.Handler | None = None,
) -> None:
```

설계서 요구사항대로 `None` 기본값으로 추가되어 CLI 호환성이 유지된다.

---

**[L128-L130] 개선: `log_handler`가 루트 logger가 아닌 `logger`(translate 모듈 로거)에만 추가됨**

```python
logger.addHandler(log_handler)
```

`src.chunker`, `src.translator` 등 하위 모듈은 자체 `logger = logging.getLogger(__name__)`를 가진다. `translate.py`의 logger에만 핸들러를 붙이면 하위 모듈 로그가 UI에 전달되지 않는다. 루트 로거에 추가하면 uvicorn 자체 로그도 포함되어 노이즈가 심해지므로, `src` 패키지 루트 로거에 추가하는 것이 적절하다.

```python
# 수정
src_logger = logging.getLogger('src')
src_translate_logger = logging.getLogger('translate')
if log_handler:
    log_handler.setLevel(logging.INFO)
    src_logger.addHandler(log_handler)
    src_translate_logger.addHandler(log_handler)

try:
    ...
finally:
    if log_handler:
        src_logger.removeHandler(log_handler)
        src_translate_logger.removeHandler(log_handler)
```

---

### run.sh

**[L19] 보안: `--host 0.0.0.0` 모든 인터페이스 바인딩**

```bash
./venv/bin/python3 -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

개발 환경에서 로컬 전용 서비스임에도 `0.0.0.0`으로 바인딩하면 같은 네트워크의 모든 기기에서 접근 가능하다. `127.0.0.1`로 변경하거나 명시적 선택지로 분리해야 한다.

```bash
# 권장
./venv/bin/python3 -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

---

**[L19] 개선: `--reload` 옵션이 프로덕션 사용 시에도 활성화됨**

`--reload`는 개발 전용 옵션이다. 환경 변수(`APP_ENV=development`)로 분기하거나 별도 `run-dev.sh`를 만드는 것을 권장한다.

---

### requirements.txt

**누락: `python-multipart` 있음 (Form/File 업로드에 필수)**

`python-multipart>=0.0.9` 포함됨 — 확인.

**[권장] 버전 상한 없음**

모든 의존성이 `>=`만 명시되어 있어 주요 버전 업그레이드 시 호환성 깨질 수 있다. `fastapi>=0.115,<1.0` 형태로 상한을 추가하거나 `requirements.lock`을 별도 관리하는 것을 권장한다.

---

## 설계 준수 여부

| 필수 항목 | 설계 요구사항 | 구현 상태 | 판정 |
|----------|-------------|----------|------|
| #1 Path Traversal | `Path(file.filename).name` 사용 | server.py L73 정확히 구현 | 통과 |
| #2 파일 크기 제한 | 50MB 상한 적용 | 메모리 선적재 후 체크 (방법 A) — DoS 잠재성 있음 | 부분 통과 |
| #3 SSE I/O 블로킹 | `asyncio.to_thread(load_progress)` | server.py L186 구현됨 | 통과 |
| #4 동시 번역 제한 | `asyncio.Semaphore(2)` | server.py L47 + L140 구현됨 | 통과 |
| #5 Task 누수 정리 | 24h 후 작업 + 파일 제거 | input_path만 제거, output/checkpoint 누락 | 부분 통과 |
| #6 task_id 12자 | `[:12]` | server.py L74 구현됨 | 통과 |
| #7 output_path에 task_id | `{task_id}_{stem}_kr.epub` | server.py L75 구현됨 | 통과 |
| #8 CORS env | `CORS_ORIGINS` 환경변수 | server.py L34-L36 구현됨 | 통과 |
| #9 log_buffer 스냅샷 | 단일 `list()` 복사 | server.py L191 구현됨 | 통과 |
| #11 SSE 재연결 5회 | `reconnectCount > 5` | app.js L95 구현됨 | 통과 |

**추가 설계 불일치:**
- `checkpoint_path`에 `task_id` 미포함 → 동일 파일 동시 번역 시 충돌
- `get_all_tasks()` 반환 타입 설계서(`list`) vs 구현(`dict`) 불일치
- `TaskInfo.log_cursor` 설계서에 명시되었으나 구현에서 제거됨

---

## 보안 체크

- [통과] SQL 인젝션 — DB 미사용
- [통과] XSS — `_escapeHtml()` 헬퍼 전반적으로 사용, `innerHTML`에 서버 데이터 삽입 시 이스케이프 확인됨
- [주의] 하드코딩된 시크릿 — 없음. API 키는 Form으로 전달되며 메모리에만 유지
- [통과] Path Traversal — `Path(file.filename).name` 적용
- [주의] 입력 검증 — `provider` enum 검증 없음, max_words 범위 검증 없음 (0 또는 음수 가능)
- [주의] SSRF — `client.check_connection()`에서 `endpoint` URL을 서버가 직접 호출. 내부 네트워크 접근 가능성

---

## 수정 요청

### [필수] 반드시 고쳐야 할 항목

**1. cleanup에서 output_path, checkpoint_path 삭제 누락 (server.py L85-L92)**

디스크 공간이 무한 증가한다. 세 경로 모두 정리하도록 수정.

**2. cleanup에서 `tasks.pop()`이 `_tasks` 직접 수정 — race condition (server.py L66, task_manager.py)**

`get_all_tasks()`가 `_tasks` 참조를 반환하므로 외부에서 직접 pop하는 구조다. `task_manager.py`에 `remove_task(task_id)` 함수를 추가하고 cleanup에서 호출해야 한다.

```python
# task_manager.py 추가
def remove_task(task_id: str) -> "TaskInfo | None":
    return _tasks.pop(task_id, None)
```

**3. `checkpoint_path`에 task_id 없음 — 동시 번역 충돌 (server.py L125)**

같은 파일명을 동시에 두 번 번역하면 체크포인트 충돌로 데이터가 손상된다.

```python
checkpoint_path = os.path.join(CHECKPOINT_DIR, f"{task_id}_{stem}_progress.json")
```

**4. SSE `error` 이벤트 핸들러와 `onerror` 혼용 — 일시적 네트워크 단절 시 연결 강제 종료 (app.js L132-L141)**

`e.data`가 없는 네트워크 에러도 `status('failed')`로 처리되어 진행 중인 번역을 사용자가 추적할 수 없게 된다.

**5. `list_checkpoints`에서 동기 I/O 블로킹 (server.py L256-L274)**

`glob.glob()` + `load_progress()` 루프를 `asyncio.to_thread`로 래핑해야 한다.

---

### [권장] 가능하면 수정할 항목

**6. `client.check_connection()` asyncio.to_thread 래핑 (server.py L159)**

5초 동기 블로킹이 이벤트 루프를 멈춘다.

**7. `log_handler`를 `src` 패키지 루트 로거에도 추가 (translate.py L128)**

하위 모듈(`src.translator` 등)의 로그가 UI에 전달되지 않는다.

**8. run.sh에서 `--host 127.0.0.1`로 변경 (run.sh L19)**

개발용 도구를 LAN에 노출하지 않아야 한다.

**9. `max_words` 입력값 범위 검증 추가 (server.py L111)**

`0` 또는 음수가 들어오면 청크 분할 로직에서 예외가 발생할 수 있다.

```python
if not (100 <= max_words <= 5000):
    raise HTTPException(400, "max_words는 100~5000 범위여야 합니다.")
```

---

## Gemini 리뷰 의견

Gemini 2.5 Flash에 `server.py`, `task_manager.py`, `translate.py`, `static/app.js` 전문을 전달하여 교차 리뷰를 수행했다.

**주요 지적 사항 (Gemini):**

1. **파일 크기 제한 방식:** Sonnet과 동일하게 메모리 선적재 방식의 DoS 위험 지적. 청크 단위 스트리밍 저장으로 수정 권장.
2. **Task 정리 불완전:** Sonnet과 동일하게 output_path, checkpoint_path 미삭제 지적.
3. **`_tasks` 경쟁 조건:** `asyncio.Lock`으로 딕셔너리 전체 접근 보호 권장. `cleanup_loop`과 일반 요청 처리가 동시에 접근할 수 있음을 강조.
4. **`list_checkpoints` 블로킹 I/O:** Sonnet과 동일하게 지적.
5. **`client.check_connection()` 블로킹:** Sonnet과 동일하게 지적.
6. **XSS:** `_escapeHtml()` 사용이 양호하다고 평가 — Sonnet과 동일한 판단.
7. **API 키 처리:** 클라이언트에서 폼으로 전달하는 방식이 HTTPS 없으면 위험하다고 지적. 개인용 도구이면 수용 가능.
8. **로깅 일관성:** 전체 애플리케이션에 대한 일관된 로깅 설정 부재 지적.
9. **환경변수화:** UPLOAD_DIR, OUTPUT_DIR, CHECKPOINT_DIR 하드코딩 개선 권장.
10. **SSE 리소스:** 양측 모두 잘 관리되고 있다고 평가.

---

## 모델 간 리뷰 비교

| 관점 | Sonnet | Gemini | 최종 판단 |
|------|--------|--------|----------|
| Path Traversal | 통과 | 통과 | 동일 — 올바르게 구현됨 |
| 파일 크기 제한 | 부분 통과 (DoS 잠재성) | 부분 통과 (청크 스트리밍 강권) | 동일 — [권장] 개선 |
| SSE I/O 블로킹 | 통과 | 통과 | 동일 — 올바르게 구현됨 |
| 동시 번역 세마포어 | 통과 | 통과 | 동일 — 올바르게 구현됨 |
| Task 정리 불완전 | 필수 수정 | 필수 수정 | 동일 — output/checkpoint 미삭제 |
| _tasks race condition | cleanup pop 구조 지적 | asyncio.Lock 전면 도입 권장 | Gemini가 더 강경 — 현실적 위험은 낮으나 개선 권장 |
| checkpoint_path 충돌 | 필수 수정 | 미지적 | Sonnet 추가 발견 |
| SSE error/onerror 혼용 | 필수 수정 | 미지적 | Sonnet 추가 발견 |
| list_checkpoints 블로킹 | 필수 수정 | 필수 수정 | 동일 |
| check_connection 블로킹 | 권장 수정 | 필수 수정 | Gemini가 더 강경 |
| 로깅 일관성 | translate.py log_handler 범위 지적 | 전체 설정 일관성 지적 | 보완적 — 둘 다 반영 |
| XSS 방어 | 양호 | 양호 | 동일 — 통과 |
| run.sh 0.0.0.0 | 권장 수정 | 미지적 | Sonnet 추가 발견 |
