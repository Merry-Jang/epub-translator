# 자료조사 보고서 — kindle-translator

## 프로젝트 개요

개인이 구매한 킨들 영문 전자책(.epub)을 MLX-LM 로컬 LLM으로 자동 한국어 번역하는 파이프라인 구축.

**핵심 요구사항:**
- EPUB 파일 읽기/쓰기 (원본 구조/메타데이터 유지)
- 텍스트 청크 분할 및 번역 품질 최적화
- MLX-LM OpenAI 호환 API 호출 (localhost:8080)
- Qwen3.5-35B 모델 사용 (thinking 모드 비활성화)
- 중단/재시작 가능한 체크포인트 시스템

---

## 기존 코드베이스 분석

프로젝트 초기 단계로 기존 코드 없음. 다음 디렉토리 구조 확보:
- `src/` — 메인 파이프라인 코드 예정
- `tests/` — 유닛 테스트 예정
- `docs/` — 설계/자료조사 문서

Python 환경: 3.12.11 (pyenv)

---

## 외부 자료

### EPUB 파싱 라이브러리

1. **EbookLib** (Python EPUB 표준 라이브러리)
   - GitHub: [aerkalov/ebooklib](https://github.com/aerkalov/ebooklib)
   - PyPI: [EbookLib](https://pypi.org/project/EbookLib/)
   - 문서: [docs.sourcefabric.org/projects/ebooklib](http://docs.sourcefabric.org/projects/ebooklib/en/latest/)
   - EPUB2/EPUB3 지원, 메타데이터/목차/spine 조작 가능

2. **BeautifulSoup4**
   - HTML/XML 파싱용 보조 라이브러리
   - EPUB 내 XHTML 콘텐츠 추출 및 수정

### EPUB 구조 레퍼런스

- [EPUB 파일의 구조 및 요소별 기능](https://www.epubguide.net/3)
- [Anatomy of an EPUB 3 file – EDRLab](https://www.edrlab.org/open-standards/anatomy-of-an-epub-3-file/)
- EPUB 내부 구조: `mimetype` + `META-INF/` + `OEBPS/`
  - `content.opf` — 메니페스트, spine, 메타데이터
  - `toc.ncx` — 목차 정보
  - 챕터 HTML 파일들 (text01.xhtml, text02.xhtml 등)

### MLX-LM OpenAI 호환 API

- GitHub: [cubist38/mlx-openai-server](https://github.com/cubist38/mlx-openai-server)
- PyPI: [mlx-openai-server](https://pypi.org/project/mlx-openai-server/)
- 엔드포인트: `http://localhost:8080/v1/chat/completions`
- Python OpenAI 클라이언트 호환

### LLM 번역 및 청크 분할

- [LLM Context Windows 정의 및 중요성](https://kr.appen.com/blog/context-windows/)
- [텍스트 분할 가이드](https://wikidocs.net/233776)
- [LLM 기반 의미론적 분할](https://github.com/Theeojeong/llm-chunker)

### Qwen3 Thinking 모드 비활성화

- [Disabling reasoning of Qwen3 in vLLM](https://discuss.vllm.ai/t/disabling-reasoning-of-qwen3-vl-8b-thinking-per-request/1800)
- [HuggingFace — How to disable or reduce thinking](https://huggingface.co/Qwen/Qwen3.5-9B/discussions/13)
- 방법: `enable_thinking=False` tokenizer 파라미터 또는 `/no_think` 프롬프트 접두어

### LLM 번역 프롬프트 베스트 프랙티스

- [LLM 시스템 프롬프트의 중요성](https://blog-ko.superb-ai.com/understanding-system-prompts-llm-response-determination/)
- [프롬프트 엔지니어링 가이드](https://www.promptingguide.ai/introduction/settings)

### LLM 샘플링 파라미터

- [Temperature, Top-P, Top-K 상세 설명](https://machinelearningplus.com/gen-ai/llm-temperature-top-p-top-k-explained/)
- [LLM 파라미터 튜닝 가이드](https://www.phdata.io/blog/how-to-tune-llm-parameters-for-top-performance-understanding-temperature-top-k-and-top-p/)

---

## 기술 스택 추천

### 최종 선택

| 항목 | 선택 | 이유 |
|------|------|------|
| **EPUB 파싱** | EbookLib + BeautifulSoup4 | 표준 조합, 안정적, 많은 레퍼런스 |
| **LLM API 클라이언트** | Python `openai` 라이브러리 | MLX-LM이 OpenAI 호환 → 기존 생태계 활용 |
| **청크 분할 전략** | 문단 + 문장 하이브리드 | 균형있는 컨텍스트 + 번역 품질 |
| **진행 추적** | JSON 체크포인트 파일 | 간단하고 확장 가능 |
| **동시성** | asyncio (I/O) 또는 ThreadPoolExecutor | 네트워크 I/O 최적화 |

### 대안 검토

**Tailored LLM 청크 분할:**
- `llm-chunker` 라이브러리로 의미론적 분할 가능
- 장점: 문맥 경계 존중
- 단점: 추가 LLM 호출 오버헤드 (비용↑, 속도↓)
- **선택 사유:** 초기 단계에는 단순 휴리스틱이 충분, 필요 시 나중에 추가

---

## 아키텍처 추천

### 파이프라인 구조

```
1. EPUB 로드 (EbookLib)
   ↓
2. 챕터별 XHTML 추출 (BeautifulSoup4)
   ↓
3. 텍스트 청크 분할 (문단 → 문장)
   ↓
4. 체크포인트 확인 (JSON) → 이미 번역된 청크 스킵
   ↓
5. MLX-LM에 배치 호출 (asyncio 병렬화)
   ↓
6. 번역 결과 병합 (원본 XHTML 구조 유지)
   ↓
7. 체크포인트 업데이트
   ↓
8. 번역본 EPUB 재생성 (EbookLib)
```

### 핵심 설계 결정

1. **청크 단위:** 문단 (기본) + 문장 분할 (길이 초과 시)
2. **컨텍스트 전달:** 이전 2문장 포함 (번역 일관성)
3. **병렬화:** MLX-LM 서버가 단일 인스턴스 → ThreadPoolExecutor + 큐 시스템
4. **메타데이터:** 원본 OPF/NCX 완전 보존

---

## 개발 방법론 추천

### 프로토타입 우선 + TDD 하이브리드

**이유:**
- EPUB 조작 및 텍스트 정제는 불확실성 높음 (프로토타입 필요)
- MLX-LM API 호출과 번역 품질은 테스트 필수 (TDD)
- 중단/재시작 로직은 복잡 → 명확한 시나리오 필요

**단계:**
1. **Week 1: 프로토타입** — EPUB 읽기 → 텍스트 추출 → 단일 청크 번역
2. **Week 2: 코어 로직 + 테스트** — 청크 분할, 체크포인트, 배치 호출
3. **Week 3: 통합 + 재결합** — 번역본 EPUB 쓰기, 메타데이터 유지
4. **Week 4: 검증 + 최적화** — 실제 킨들 책 테스트, 품질 튜닝

---

## 리스크 & 주의사항

### 기술적 난이도

| 영역 | 난이도 | 주의사항 |
|------|--------|---------|
| **EPUB 구조 유지** | 중 | OPF manifest ID/href 불일치 → 뷰어 인식 실패. 테스트 필수 |
| **텍스트 인코딩** | 중 | EPUB 내 UTF-8/ISO-8859-1 혼재 가능 → BeautifulSoup4의 자동 감지 신뢰 |
| **LLM 할루시네이션** | 중 | 단순 프롬프트만으로는 번역 오류 발생 → 프롬프트 튜닝 필수 |
| **체크포인트 동시성** | 중 | 다중 스레드 → JSON 파일 경합(race condition) 가능. Lock 필요 |

### 알려진 이슈

1. **Qwen3 thinking 모드**
   - `enable_thinking=False` 설정 필수
   - 미설정 시 불필요한 토큰 소모 (번역 시간 ↑)

2. **EPUB 내 CSS 스타일**
   - 번역 과정에서 CSS는 변경 안 됨 (올바름)
   - 스타일이 한국 글씨체에 최적화 안 될 수 있음
   - **권장:** 번역 후 폰트/여백 수동 조정 (별도 스텝)

3. **이미지/오디오 파일**
   - EbookLib는 바이너리 파일 (이미지/음성) 복사만 함 (수정 안 함)
   - 예상 동작 (올바름)

4. **장문 챕터**
   - 3000+ 단어 챕터 → 청크 분할 후 문맥 단절 가능
   - **권장:** 문단 경계 + 슬라이딩 윈도우(overlap) 고려

### 의존성 충돌

- EbookLib + BeautifulSoup4 → 모두 오래되고 안정적 (충돌 낮음)
- MLX-LM 서버 → MLX 라이브러리 별도 설치 필요 (이미 사용자 환경에 설치됨)

---

## 최종 추천 기술 스택 및 구현 전략

### 라이브러리 선택 최종본

```python
# 필수
pip install ebooklib beautifulsoup4 openai

# 선택사항 (추후)
pip install tqdm  # 진행률 표시
```

### 번역 프롬프트 예시

**시스템 프롬프트:**
```
당신은 영문 전자책을 정확하고 자연스러운 한국어로 번역하는 전문 번역가입니다.

## 지침:
1. 원문의 의미와 톤을 정확히 전달할 것
2. 기술 용어는 일반적인 번역을 사용하고, 괄호에 원문 병기 (예: interface(인터페이스))
3. 인명, 지명은 원문 그대로 유지
4. 문단 구조와 라인 브레이크는 원문과 동일하게 유지

이전 문맥:
{previous_text}

다음 텍스트를 번역하세요:
```

**사용자 메시지:**
```
[번역할 텍스트]
```

### 샘플 API 호출 (Python)

```python
from openai import OpenAI

client = OpenAI(
    api_key="not-needed",  # MLX-LM은 API 키 불필요
    base_url="http://localhost:8080/v1"
)

response = client.chat.completions.create(
    model="mlx-community/Qwen3.5-35B-A3B-4bit",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text_to_translate}
    ],
    temperature=0.1,  # 정확도 우선 (낮은 값)
    top_p=0.3,         # 결정적 출력
    max_tokens=2000,
)

translated = response.choices[0].message.content
```

### 체크포인트 설계 제안

**JSON 구조:**
```json
{
  "epub_path": "/path/to/input.epub",
  "output_path": "/path/to/output.epub",
  "metadata": {
    "total_chapters": 15,
    "total_chunks": 342,
    "started_at": "2026-03-29T14:30:00Z"
  },
  "progress": {
    "completed_chunks": 127,
    "current_chapter": 5,
    "failed_chunks": [
      {"chunk_id": "ch3_p2_s1", "error": "timeout", "retry_count": 2}
    ]
  },
  "translations": {
    "ch1_p1_s1": "번역된 텍스트...",
    "ch1_p1_s2": "번역된 텍스트..."
  }
}
```

**재시작 로직:**
```python
# 체크포인트 로드 시
if checkpoint_exists:
    completed = set(checkpoint['translations'].keys())
    failed = {item['chunk_id']: item['retry_count']
              for item in checkpoint['progress']['failed_chunks']}

    for chunk in all_chunks:
        if chunk.id in completed:
            # 스킵
            continue
        elif chunk.id in failed and failed[chunk.id] >= 3:
            # 3회 이상 실패 → 수동 검토 대기
            log.warning(f"Chunk {chunk.id} failed 3 times, skipping")
            continue
        else:
            # 번역 시도
            translate(chunk)
```

### 주요 파일 구조

```
kindle-translator/
├── src/
│   ├── epub_handler.py          # EPUB 읽기/쓰기
│   ├── text_splitter.py         # 청크 분할
│   ├── translator.py            # MLX-LM API 호출
│   ├── checkpoint.py            # 진행 추적
│   └── pipeline.py              # 메인 파이프라인
├── tests/
│   ├── test_epub_handler.py
│   ├── test_text_splitter.py
│   └── test_translator.py
├── docs/
│   ├── 01-research.md           # 이 문서
│   ├── 02-design.md             # 상세 설계
│   └── examples/                # 샘플 EPUB 파일
└── .checkpoints/                # 진행 저장 디렉토리
```

---

## Gemini 조사 의견

Gemini(gemini-2.5-flash)로 동일 주제에 대해 병렬 조사를 수행한 결과:

### Gemini의 핵심 조언

#### 1. EPUB + 청크 분할
- **EbookLib + BeautifulSoup4 조합 강력 추천** (Haiku와 일치)
- **HTML 구조 보존의 중요성 강조** — 단순 텍스트만 추출하면 `<b>`, `<i>`, 링크 등 포맷팅 손실
- **실무 기법:** BeautifulSoup으로 텍스트 노드만 찾아 번역하고, HTML 태그는 그대로 유지
- **컨텍스트 전략:** 이전 2문장 + 원본 전체 문단 포함 권장

#### 2. 번역 품질 최적화
- **Temperature 0.1 + Top_p 0.3 적절함** (Haiku 일치)
- **추가 중요 파라미터:**
  - `max_new_tokens`: 원문의 1.5~2배 또는 고정값 2048~4096 설정 필수
  - `repetition_penalty`: 1.1~1.2 추가 권장 (반복 방지)
  - Beam search (num_beams=2~5) 고려 시 품질↑, 속도↓
- **Qwen thinking 모드 비활성화: 필수** (Haiku와 동일)

#### 3. 프롬프트 엔지니어링 (중요)
Gemini가 강조한 실무 기법:

**System Prompt:**
```
You are a professional English-to-Korean translator.
Your task is to translate the provided English text into
natural, fluent, and accurate Korean.
Maintain the original meaning, tone, and formatting
(e.g., <b>, <i>, <a href="...">) precisely.
Do not add or omit any information.
Only provide the translated Korean text.
```

**User Prompt with Context:**
```
Translate the following English text to Korean:

[CONTEXT]
{이전 2 문장 또는 원본 이전 문단}
[/CONTEXT]

[TARGET TEXT TO TRANSLATE]
{번역할 청크 — HTML 태그 포함}
[/TARGET TEXT TO TRANSLATE]

Korean Translation:
```

**용어집 추가 권장** (선택사항이지만 품질↑):
```
Glossary:
- "Neuralink": 뉴럴링크
- "SpaceX": 스페이스X
```

#### 4. 체크포인트 + Race Condition
Gemini의 실무 기법 (Haiku보다 상세):

**방법 1: Lock 사용**
```python
import threading
checkpoint_lock = threading.Lock()

def update_checkpoint(chunk_id, status, translated_text=None):
    with checkpoint_lock:  # Critical section
        # JSON 읽기 → 수정 → 쓰기
        data = load_json(...)
        data[chunk_id] = {...}
        save_json(data, ...)
```

**방법 2: Atomic Write (더 강력)**
```python
import tempfile, os
with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
    json.dump(data, tmp)
os.replace(tmp.name, checkpoint_file)  # 원자적 치환
```

**방법 3: 청크별 독립 파일**
- 각 청크를 개별 `.json`으로 저장 (race condition 완전 회피)
- 최종 병합 시 순서대로 모음

#### 5. EPUB 재조립 (핵심 경고)
- **텍스트 노드만 교체** — HTML 태그는 건드리지 않기
- **메타데이터:** `dc:language` 만 `en` → `ko` 변경, 나머지는 보존
- **인코딩:** 반드시 UTF-8 (XHTML 내 `<meta charset="utf-8"/>` 확인)
- **반드시 테스트:** 여러 EPUB 뷰어 (Calibre, Kindle, 모바일 등)에서 검증

#### 6. ThreadPoolExecutor 최적화
- MLX-LM 서버가 여러 동시 요청 지원하지만, GPU 자원에 따라 병목
- `max_workers` 값을 GPU 사용량 모니터링하며 조정 필요
- Exponential backoff 재시도 권장 (일시적 네트워크 문제 대응)

---

## 모델 간 비교 (Haiku vs Gemini)

| 항목 | Haiku (Claude) | Gemini | 채택 |
|------|---|---|---|
| **EPUB 파싱** | EbookLib + BeautifulSoup4 | 동일 강력 추천 | ✅ Haiku 권장 추종 |
| **HTML 구조 유지** | 언급 안 함 | **상세 강조** — 텍스트 노드만 교체 | 🔴 **Gemini 통합** |
| **Temperature** | 0.1 (정확도) | 동일 | ✅ 합의 |
| **Top_p** | 0.3 | 동일 | ✅ 합의 |
| **추가 파라미터** | 언급 안 함 | max_tokens, repetition_penalty, beam search | 🔴 **Gemini 추가** |
| **Thinking 모드** | 비활성화 필수 | 필수 강조 | ✅ 합의 |
| **프롬프트** | 기본 예시 | **상세 시스템/사용자 프롬프트** | 🔴 **Gemini 우수** |
| **체크포인트** | JSON + Lock 제안 | Lock / Atomic / 개별파일 3가지 | 🔴 **Gemini 상세** |
| **Race Condition** | Lock 기본 | Lock/Atomic/개별파일 + 코드 예시 | 🔴 **Gemini 상세** |
| **ThreadPoolExecutor** | 기본 병렬화 | GPU 모니터링 + Exponential backoff | 🔴 **Gemini 실무적** |
| **아키텍처** | 파이프라인 흐름도 | 동일 + 용어집/프로토타입 추천 | ✅ 합의 |

---

## 최종 추천 (Haiku + Gemini 병합)

### 1. 기술 스택 (확정)

```python
# 필수
pip install ebooklib beautifulsoup4 openai

# 선택 (모니터링)
pip install tqdm psutil
```

### 2. 핵심 구현 전략 (병합)

#### EPUB 처리
- **텍스트 노드만 추출/번역** (Gemini 강조)
- BeautifulSoup으로 각 HTML 요소를 반복하며:
  ```python
  for text_node in soup.find_all(string=True):
      if text_node.parent.name not in ['script', 'style']:
          # 텍스트만 번역하고 교체
  ```
- HTML 구조는 절대 변경 금지

#### 프롬프트 (Gemini 상세 버전 채택)
- System: 번역가 페르소나 + 형식 유지 명시
- User: [CONTEXT] + [TARGET] 분리
- 용어집 추가 (특정 도메인 용어 있을 시)

#### 샘플링 파라미터 (병합)
```python
response = client.chat.completions.create(
    model="mlx-community/Qwen3.5-35B-A3B-4bit",
    messages=[...],
    temperature=0.1,
    top_p=0.3,
    max_tokens=2048,           # Gemini 추가
    repetition_penalty=1.1,    # Gemini 추가
    # num_beams=2,            # 선택 (속도 vs 품질)
)
```

#### 체크포인트 (Atomic Write 권장)
```python
import tempfile, os

def atomic_checkpoint_save(checkpoint_data):
    """Race condition 없이 체크포인트 저장"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
        json.dump(checkpoint_data, tmp, indent=2, ensure_ascii=False)
    os.replace(tmp.name, 'translation_progress.json')
```

#### 병렬 처리 (모니터링 추가)
```python
from concurrent.futures import ThreadPoolExecutor
import psutil
import time

# GPU 사용량 모니터링하며 max_workers 조정
# 초기값: 4~8, GPU 사용량 < 90%일 때만 증가
def get_optimal_workers():
    gpu_usage = psutil.virtual_memory().percent
    return 4 if gpu_usage < 80 else 2
```

#### Exponential Backoff 재시도 (Gemini 권장)
```python
import time

def translate_with_retry(chunk, max_retries=3):
    for attempt in range(max_retries):
        try:
            return translate(chunk)
        except Exception as e:
            wait_time = 2 ** attempt  # 1s, 2s, 4s
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                raise
```

### 3. 개발 우선순위

1. **Week 1:** EPUB 읽기 → HTML 구조 보존 검증 (프로토타입)
2. **Week 2:** 프롬프트 엔지니어링 + 샘플링 파라미터 튜닝 (TDD)
3. **Week 3:** 청크 분할 + 체크포인트 + 병렬화 (코어)
4. **Week 4:** EPUB 재조립 + 여러 뷰어 테스트 (검증)

### 4. 주의사항 (통합)

| 항목 | Haiku | Gemini | 행동 |
|------|-------|--------|------|
| HTML 구조 | 기본 | ⚠️ 상세 경고 | 텍스트 노드만 교체 필수 |
| 프롬프트 | 기본 | 🔴 상세 제시 | Gemini 버전 사용 |
| 파라미터 | 기본 | 🔴 max_tokens, repetition_penalty 추가 | 병합 적용 |
| 재시도 | 기본 | Exponential backoff | Gemini 기법 채택 |
| 테스트 | 일반 | 🔴 여러 뷰어 명시 | Calibre, Kindle, 모바일 검증 |

---

## 다음 단계

1. **설계 단계** (Designer) — 상세 API 스펙, 프롬프트 최종본, 파일 구조 정의
2. **설계 검토** (Reviewer) — Gemini 조언 통합 검증
3. **사용자 승인** — 병합된 기술 스택 최종 확인
4. **개발 단계** (Developer) — 병합된 전략으로 구현
5. **테스트** (Tester) — 여러 EPUB 뷰어 호환성 검증
6. **최종 검증** — 실제 킨들 책 end-to-end 테스트
