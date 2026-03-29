# Phase 2 자료조사 — Gradio → FastAPI + Custom HTML UI 전환

**작성일:** 2026-03-29
**대상:** Kindle 번역기 UI 현대화 프로젝트 (Phase 2)
**범위:** Gradio 제거 후 FastAPI 백엔드 + 커스텀 HTML/Tailwind 프론트엔드 구축

---

## 프로젝트 개요

### Phase 1 상태 (현재)
- **백엔드:** Python Gradio 4.0 (고수준 래퍼)
- **파이프라인:** `translate.py` 동기식, 체크포인트 기반 이어하기 구현
- **상태 관리:** 파일 스코프 전역변수 (`_is_translating`, `_translation_lock`)
- **진행 추적:** JSON 체크포인트 파일 + Gradio Timer (5초 폴링)

### Phase 2 목표
- **백엔드:** FastAPI로 전환 (REST API 기반)
- **프론트엔드:** 커스텀 HTML + Tailwind CDN + Vanilla JS
- **실시간 통신:** SSE (Server-Sent Events) 또는 WebSocket으로 진행률 스트리밍
- **중단/재개:** 번역 중단 버튼 추가 + 비동기 취소 메커니즘

---

## 1. 기존 코드베이스 분석

### 핵심 함수 호출 체인

```
app.py (Gradio UI)
  ├── translate_epub() [이벤트 핸들러]
  │   └── run_pipeline() [translate.py]
  │       ├── parse_epub()
  │       ├── chunk_chapter()
  │       ├── [for chunk in all_chunks]
  │       │   └── translate_chunk()
  │       │       └── client.complete() [LLMClient]
  │       └── build_epub()
  └── check_status() [체크포인트 읽기]
```

### 병목 분석

| 영역 | 현황 | Phase 2 개선 |
|------|------|-----------|
| **UI 블로킹** | Gradio가 Python 함수를 동기식으로 호출 | FastAPI async 엔드포인트로 논블로킹화 |
| **진행 추적** | 5초 폴 (타이머) | SSE 푸시 기반 (즉시 반영) |
| **중단 불가** | 진행 중인 루프 강제 중단 불가 | asyncio.Task + cancellation 토큰 |
| **수동 상태 관리** | `_translation_lock` 스레드 락 | asyncio.Lock으로 단순화 |

### 재사용 가능한 코드

- `translate.py` **전체** — 파이프라인 로직 자체는 프로바이더 독립적
  - `run_pipeline()` → FastAPI 엔드포인트 내부에서 비동기 래핑
  - `translate_chunk()` → 변경 불필요
  - `LLMClient` → 변경 불필요
- `src/` 모듈 **전체** — EPUB 처리, 청크 분할, 빌드 등 재사용
- `checkpoints/` 시스템 → JSON 형식 유지, SSE로 실시간 반영

---

## 2. FastAPI + SSE/WebSocket 패턴 조사

### SSE vs WebSocket 비교

| 항목 | SSE | WebSocket |
|------|-----|-----------|
| **통신 방향** | 단방향 (서버 → 클라이언트) | 양방향 (실시간 메시지) |
| **구현 복잡도** | 낮음 (HTTP, EventSource API) | 높음 (핸드셰이크, 프로토콜 업그레이드) |
| **진행률 스트리밍** | ✅ 최적 | ⚠️ 과도 |
| **초기 지연 (TTFB)** | 빠름 (프로토콜 업그레이드 없음) | 느림 (핸드셰이크 오버헤드) |
| **동시 연결 수** | 100K+ (벤치마크) | ~12K (벤치마크) |
| **브라우저 지원** | 모든 최신 브라우저 | 모든 최신 브라우저 |

**결론:** 진행률/상태만 필요 → **SSE 권장**

### FastAPI SSE 구현 패턴

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

@app.post("/translate")
async def translate_epub(file: UploadFile):
    # 1. 파일 저장
    # 2. asyncio.create_task()로 백그라운드 작업 시작
    # 3. SSE 제너레이터 반환
    
    async def progress_stream():
        while task_running:
            checkpoint_data = load_progress(checkpoint_path)
            progress = {
                "completed": checkpoint_data["completed_chunks"],
                "total": checkpoint_data["total_chunks"],
                "status": "translating"
            }
            yield f"data: {json.dumps(progress)}\n\n"
            await asyncio.sleep(1)  # 1초마다 업데이트
    
    return StreamingResponse(
        progress_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )
```

### 백그라운드 작업 관리

**문제:** FastAPI의 `BackgroundTasks`는 시작 후 제어 불가

**솔루션:** `asyncio.create_task()` + `asyncio.Event` 조합

```python
# 전역 작업 관리
active_translations = {}  # task_id → (task, cancel_event)

@app.post("/translate")
async def translate_epub(file: UploadFile):
    task_id = str(uuid.uuid4())
    cancel_event = asyncio.Event()
    
    async def translation_task():
        try:
            await run_pipeline_async(
                input_path,
                output_path,
                cancel_event  # 취소 신호
            )
        finally:
            del active_translations[task_id]
    
    task = asyncio.create_task(translation_task())
    active_translations[task_id] = (task, cancel_event)
    
    return {"task_id": task_id}

@app.post("/cancel/{task_id}")
async def cancel_translation(task_id: str):
    if task_id in active_translations:
        task, cancel_event = active_translations[task_id]
        cancel_event.set()  # 신호 전송
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
        return {"status": "cancelled"}
```

### 파이프라인 비동기화 전략

**현재:** `run_pipeline()` 동기식 (for 루프)

**Phase 2:**
1. `translate_chunk()` 자체는 동기식 유지 (LLM 호출은 동기)
2. `run_pipeline()` 래퍼를 async def로 작성
3. 루프 내에서 `asyncio.sleep(0)` 또는 `await asyncio.to_thread()` 삽입
   - 취소 신호 체크 포인트 제공
   - 이벤트 루프에 제어권 반환

```python
async def run_pipeline_async(
    ...,
    cancel_event: asyncio.Event
):
    for chunk in all_chunks:
        # 취소 신호 확인
        if cancel_event.is_set():
            logger.info("번역 취소됨")
            break
        
        # 동기 작업을 스레드 풀에서 실행
        translated_text = await asyncio.to_thread(
            translate_chunk,
            chunk, client, model
        )
        
        # 체크포인트 저장 (빠른 작업)
        save_progress(checkpoint_path, checkpoint_data)
        
        # 이벤트 루프에 제어권 반환
        await asyncio.sleep(0)
```

---

## 3. 디자인 파일 분석

### `/tmp/kindle-design/DESIGN.md` 핵심

**Creative North Star:** "The Digital Curator" — 프리미엄 에디토리얼 환경

**주요 디자인 규칙:**
1. **색상:** 깊은 네이비 베이스 (#040e1f) + 전기 사파이어 (#85adff)
2. **글자:** Manrope 폰트, 한국어는 line-height +15%
3. **요소 경계:** 보더 금지 → 배경 색상 톤 시프트로 표현
4. **유리효과:** Glassmorphism (70% 불투명 + 12px 블러)
5. **CTA 버튼:** 135° 그래디언트 + Glow Aura (box-shadow)

### `/tmp/kindle-design/code.html` 구조

```html
<nav> TopNavBar (고정, z-50)
<body> 메인 레이아웃
  <div> 왼쪽 패널 (파일 업로드, 설정)
  <div> 오른쪽 패널 (진행률, 다운로드)
```

**기능 연결점:**
- 파일 입력 필드 → FormData 수집
- "번역 시작" 버튼 → POST `/translate` (SSE 연결)
- 진행률 바 → SSE 데이터로 실시간 업데이트
- "중단" 버튼 → POST `/cancel/{task_id}`
- "다운로드" 버튼 → GET `/download/{task_id}`

---

## 4. 기술 스택 추천 (Phase 2)

### 최종 선택

| 항목 | 선택 | 이유 |
|------|------|------|
| **웹 프레임워크** | FastAPI 0.115+ | 비동기 네이티브, 프로덕션 준비, Pydantic 자동 검증 |
| **실시간 통신** | SSE (Server-Sent Events) | 단방향 진행률 스트리밍, 단순, 고성능 (100K+ 동시 연결) |
| **백그라운드 작업** | `asyncio.create_task()` + `asyncio.Event` | 세밀한 취소 제어, 구조화된 동시성 |
| **ASGI 서버** | Uvicorn | FastAPI 표준, 빠름, 프로덕션 안정 |
| **프론트엔드** | Vanilla JS + Tailwind CDN | 프레임워크 오버헤드 없음, 디자인 시스템 완성 |
| **파일 업로드** | FastAPI `UploadFile` + `StreamingResponse` | 표준, 대용량 파일 지원 |
| **진행 저장소** | JSON 체크포인트 (현재 유지) | 단순, 빠른 조회, SSE로 실시간 반영 |

### 대안 검토

#### 1. **WebSocket vs SSE**
- **선택:** SSE
- **이유:** 단방향 충분, 초기 지연 없음, 구현 단순
- **대안 사용 시:** 양방향 실시간 상호작용 필요 시 (예: 리얼타임 협업 편집)

#### 2. **BackgroundTasks vs asyncio.create_task()**
- **선택:** `asyncio.create_task()` + 수동 관리
- **이유:** 취소 제어 필요, 구조화된 동시성
- **주의:** Task 누수 방지 (try/finally에서 정리)

#### 3. **파일 스트리밍 방식**
- **선택:** `request.stream()` (대용량 EPUB 대비)
- **이유:** 메모리 효율, 청크 단위 처리 가능
- **대안:** 현재 크기 (수 MB) 내에서는 `UploadFile` 충분

---

## 5. 아키텍처 추천 (Phase 2)

### 전체 흐름

```
┌─────────────────┐
│  HTML UI        │ (Vanilla JS)
│  (Tailwind)     │
└────────┬────────┘
         │
         ├── POST /translate (FormData)
         │    ├── 파일 수신
         │    ├── Task ID 반환
         │    └── SSE 연결 시작
         │
         ├── GET /progress/{task_id} (SSE)
         │    ├── 체크포인트 읽기
         │    ├── JSON 스트리밍
         │    └── 진행률 업데이트
         │
         ├── POST /cancel/{task_id}
         │    ├── cancel_event.set()
         │    └── 상태 반환
         │
         └── GET /download/{task_id}
              └── EPUB 파일 반환

┌──────────────────────────┐
│  FastAPI Backend         │
├──────────────────────────┤
│ • run_pipeline_async()   │ (비동기 래퍼)
│ • translate_chunk()      │ (asyncio.to_thread)
│ • active_translations{}  │ (Task 관리)
└─────────────┬────────────┘
              │
              └── src/ 모듈 (재사용)
                  ├── providers.py
                  ├── translator.py
                  ├── epub_parser.py
                  ├── chunker.py
                  ├── epub_builder.py
                  └── checkpoint.py
```

### 엔드포인트 설계

#### 1. `POST /translate` — 번역 시작

**요청:**
```json
{
  "file": "<UploadFile>",
  "provider": "local",
  "model": "mlx-community/Qwen3.5-35B-A3B-4bit",
  "max_words": 800,
  "resume": false
}
```

**응답:**
```json
{
  "task_id": "uuid-1234",
  "status": "started",
  "message": "번역 시작. /progress/{task_id}로 진행률 추적"
}
```

#### 2. `GET /progress/{task_id}` — SSE 진행률

**헤더:**
```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

**데이터:**
```
data: {"completed": 50, "total": 200, "status": "translating", "failed": 0}

data: {"completed": 75, "total": 200, "status": "translating", "failed": 0}

data: {"completed": 200, "total": 200, "status": "completed", "output": "path/to/file.epub"}
```

#### 3. `POST /cancel/{task_id}` — 번역 취소

**응답:**
```json
{
  "status": "cancelled",
  "completed": 75,
  "total": 200,
  "message": "번역이 취소되었습니다"
}
```

#### 4. `GET /download/{task_id}` — 파일 다운로드

**응답:** EPUB 파일 바이너리

---

## 6. 개발방법론 추천

### 선택: **프로토타입 우선 (Prototype-First)**

**이유:**
1. **UI/UX 검증 우선:** 디자인 시스템이 완성되어 있음 → 먼저 동작하는 프로토타입으로 검증
2. **기술 리스크:** SSE + asyncio 조합은 검증되지 않음 → PoC 필요
3. **점진적 마이그레이션:** Gradio 유지 → FastAPI 병렬 개발 → 완전 전환 가능

### 개발 단계

#### Phase 2-A: FastAPI 백엔드 프로토타입 (1주)
```
1. FastAPI 프로젝트 구조
   ├── main.py (엔드포인트)
   ├── pipeline.py (run_pipeline_async)
   └── models.py (Pydantic 스키마)

2. 간단한 SSE 엔드포인트
   - MockTask로 진행률 시뮬레이션
   - JSON 스트리밍 확인

3. 취소 메커니즘
   - asyncio.Event 테스트
   - Task 정리 확인
```

#### Phase 2-B: HTML/JS 프로토타입 (1주)
```
1. 디자인 시스템 정적 HTML
   - Tailwind CDN 포함
   - 모든 컬러 토큰 적용

2. Vanilla JS 로직
   - FormData 수집
   - SSE 연결 (EventSource API)
   - 진행률 바 업데이트
   - 취소 버튼

3. 로컬 FastAPI와 통합
   - CORS 설정
   - 실제 파일 업로드
```

#### Phase 2-C: 통합 및 에러 처리 (1주)
```
1. 예외 상황 처리
   - 파일 없음
   - LLM 연결 실패
   - 네트워크 끊김 (SSE 재연결)

2. 성능 최적화
   - 청크 크기 조정
   - 메모리 프로파일링

3. 프로덕션 준비
   - Uvicorn + Nginx 구성
   - 로깅 표준화
```

---

## 7. 리스크 & 주의사항

### 기술적 리스크

| 리스크 | 심각도 | 대응 |
|--------|--------|------|
| **asyncio.to_thread() 오버헤드** | 중간 | 초기 벤치마크 필수 (5-10 청크) |
| **SSE 클라이언트 재연결** | 중간 | EventSource 재연결 로직 + 서버 상태 추적 |
| **Task 누수** | 높음 | try/finally에서 항상 정리, 타임아웃 설정 |
| **대용량 EPUB (10MB+)** | 낮음 | 스트림 방식으로 업그레이드 준비 |
| **동시 다중 번역** | 낮음 | 현재 단일 인스턴스 가정, 필요 시 Redis 큐 |

### 의존성 충돌

```
현재:                  Phase 2:
gradio==4.0     →     제거
                       fastapi==0.115+
                       uvicorn==0.28+
                       starlette==0.37+ (FastAPI 포함)
```

**주의:** Starlette 업그레이드 시 `StreamingResponse` API 확인 (안정적이나 마이너 버전 체크)

### 성능 고려사항

#### 메모리 프로필
- **Phase 1 (Gradio):** 스레드 추가 오버헤드 없음
- **Phase 2 (FastAPI):** Task 당 1-2MB (작음)
- **최악:** 100 동시 번역 = 100-200MB (무시 가능)

#### 응답 시간
- **File Upload:** 네트워크 한정 (변화 없음)
- **SSE 지연:** 1초 주기 (Gradio 5초 폴 → 개선)
- **Task 시작:** asyncio.create_task() = 밀리초 (즉시)

#### 확장성 (Future)
- **단일 인스턴스:** 10-20 동시 번역 (MLX-LM 메모리 한정)
- **멀티 인스턴스:** Redis 태스크 큐 + Celery (Phase 3+)

---

## 8. 마이그레이션 전략

### 단계별 계획

#### 1. **병렬 실행 (2주)**
```
Phase 1: Gradio 유지 (기존)
Phase 2: FastAPI + HTML/JS (신규)

둘 다 동시 실행 → 동작 비교
```

#### 2. **전환 (1주)**
```
Gradio 엔드포인트 제거
FastAPI 프로덕션화
```

#### 3. **검증 (1주)**
```
실제 EPUB 파일로 테스트
이어하기 동작 확인
중단/재개 안정성 확인
```

---

## 9. 리소스 & 레퍼런스

### FastAPI 공식 문서
- [Server-Sent Events](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- [Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse)
- [File Uploads](https://fastapi.tiangolo.com/tutorial/request-files/)

### 비동기 Python
- [asyncio 공식 문서](https://docs.python.org/3/library/asyncio-task.html)
- [Structured Concurrency (TaskGroups)](https://docs.python.org/3/library/asyncio.html#task-groups)

### 클라이언트 (Vanilla JS)
- [MDN: Server-Sent Events API](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- [EventSource 폴리필](https://github.com/mpetazzoni/sse.js/)

### 참고 자료
- [FastAPI Real-Time API: WebSockets vs SSE vs Long-Polling (2026 Guide)](https://medium.com/@rameshkannanyt0078/fastapi-real-time-api-websockets-vs-sse-vs-long-polling-2026-guide-ce1029e4432e)
- [Streaming Architecture 2026: SSE vs WebSockets](https://jetbi.com/blog/streaming-architecture-2026-beyond-websockets)
- [FastAPI Background Tasks vs Threads vs Async](https://hussainwali.medium.com/fastapi-backgroundtask-vs-threads-vs-async-f0020540bb87)
- [Implementing Server-Sent Events with FastAPI](https://mahdijafaridev.medium.com/implementing-server-sent-events-sse-with-fastapi-real-time-updates-made-simple-6492f8bfc154)
- [Real-Time Notifications in Python: Using SSE with FastAPI](https://medium.com/@inandelibas/real-time-notifications-in-python-using-sse-with-fastapi-1c8c54746eb7)
- [How to Use Background Tasks in FastAPI](https://betterstack.com/community/guides/scaling-python/background-tasks-in-fastapi/)
- [File Upload with Progress Tracking in Tailwind CSS](https://preline.co/docs/file-uploading-progress-form.html)
- [Vanilla JS Server-Sent Events Implementation](https://dev.to/serifcolakel/real-time-data-streaming-with-server-sent-events-sse-1gb2)

---

## 최종 추천 (종합)

### 기술 스택
- **백엔드:** FastAPI 0.115+ + Uvicorn
- **실시간:** SSE (진행률) + asyncio.Event (취소)
- **프론트엔드:** Vanilla JS + Tailwind CDN

### 아키텍처
- 단일 엔드포인트 기반 REST API
- 상태 저장소: JSON 체크포인트 (현재 유지)
- Task 관리: 전역 딕셔너리 + asyncio.create_task()

### 개발 방향
1. **FastAPI 백엔드 + 간단한 UI (1-2주)**
2. **Tailwind 디자인 시스템 통합 (1주)**
3. **통합 테스트 + 최적화 (1주)**

### 리스크 완화
- ✅ asyncio.to_thread() 벤치마크 필수
- ✅ SSE 재연결 로직 사전 구현
- ✅ Task 정리 규칙 엄격히 준수
- ✅ 병렬 실행 기간 동안 안정성 검증

