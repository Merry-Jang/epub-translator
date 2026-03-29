# 기술 설계서 — kindle-translator

## 설계 개요

킨들 영문 EPUB을 로컬 MLX-LM(Qwen3.5-35B)으로 한국어 번역하는 CLI 파이프라인.
EPUB 파싱 → 문단 추출 → 청크 분할 → LLM 번역 → EPUB 재조립의 5단계 순차 처리.
체크포인트로 중단/재시작을 지원하며, 원본 EPUB의 HTML 구조와 메타데이터를 완전 보존한다.

---

## 아키텍처

### 컴포넌트 다이어그램

```
┌─────────────────────────────────────────────────────┐
│                    translate.py (CLI)                │
│              argparse → 파이프라인 실행               │
└────────────────────────┬────────────────────────────┘
                         │
        ┌────────────────▼────────────────┐
        │        메인 파이프라인 루프       │
        │   (translate.py:run_pipeline)    │
        └──┬──────┬──────┬──────┬────┬────┘
           │      │      │      │    │
     ┌─────▼──┐ ┌─▼────┐│  ┌───▼──┐ │
     │ epub   │ │chunk ││  │check │ │
     │ parser │ │  er  ││  │point │ │
     └────────┘ └──────┘│  └──────┘ │
                   ┌─────▼─────┐ ┌──▼──────┐
                   │translator │ │  epub    │
                   │           │ │ builder  │
                   └─────┬─────┘ └─────────┘
                         │
                   ┌─────▼─────┐
                   │  MLX-LM   │
                   │ localhost  │
                   │   :8080   │
                   └───────────┘
```

### 데이터 플로우

```
input.epub
  │
  ▼
epub_parser.parse_epub()
  │  EbookLib로 EPUB 로드
  │  BeautifulSoup로 각 챕터 XHTML에서 블록 요소 추출
  │  → List[Chapter]
  │
  ▼
chunker.chunk_chapter()
  │  문단들을 max_words 기준으로 그룹화
  │  이전 컨텍스트(2문장) 첨부
  │  → List[Chunk]
  │
  ▼
checkpoint.load_progress()
  │  기존 체크포인트 확인 → 완료된 청크 스킵
  │
  ▼
translator.translate_chunk()  [순차 반복]
  │  MLX-LM API 호출 (OpenAI 호환)
  │  /no_think 모드로 Qwen3 thinking 비활성화
  │  재시도 로직 (exponential backoff)
  │  → 번역된 텍스트
  │
  ▼
checkpoint.save_progress()
  │  매 청크 완료 시 atomic write로 저장
  │
  ▼
epub_builder.build_epub()
  │  원본 EPUB 복사
  │  각 챕터 XHTML의 블록 요소 텍스트를 번역문으로 교체
  │  dc:language를 ko로 변경
  │  → output_kr.epub
```

---

## 파일 구조

```
kindle-translator/
├── translate.py              # CLI 진입점 (argparse + 파이프라인 실행)
├── src/
│   ├── __init__.py
│   ├── epub_parser.py        # EPUB 파싱 + 챕터/문단 추출
│   ├── chunker.py            # 문단 → 청크 분할 (max_words 기준)
│   ├── translator.py         # MLX-LM API 호출 + 번역
│   ├── epub_builder.py       # 번역본 EPUB 재조립
│   └── checkpoint.py         # 진행률 저장/로드 (atomic write)
├── tests/
│   ├── __init__.py
│   ├── test_epub_parser.py
│   ├── test_chunker.py
│   ├── test_translator.py
│   ├── test_epub_builder.py
│   └── test_checkpoint.py
├── docs/
│   ├── 01-research.md
│   └── 02-design.md          # 이 문서
├── PIPELINE.md
└── .gitignore
```

### 각 파일의 역할

| 파일 | 역할 | 의존성 |
|------|------|--------|
| `translate.py` | CLI 인터페이스, 파이프라인 오케스트레이션 | src 전체 |
| `epub_parser.py` | EPUB → Chapter 리스트 변환 | ebooklib, bs4 |
| `chunker.py` | Chapter → Chunk 리스트 분할 | 없음 (순수 Python) |
| `translator.py` | Chunk → 번역 텍스트 (API 호출) | openai |
| `epub_builder.py` | 원본 EPUB + 번역 → 새 EPUB | ebooklib, bs4 |
| `checkpoint.py` | JSON 체크포인트 읽기/쓰기 | 없음 (순수 Python) |

---

## 핵심 인터페이스

### 데이터 클래스 (`src/epub_parser.py`)

```python
from dataclasses import dataclass, field

@dataclass
class TextBlock:
    """XHTML 내 번역 가능한 블록 요소 하나"""
    index: int          # 챕터 내 순서 (0-based)
    text: str           # 블록의 inner HTML (인라인 태그 포함)
                        # 예: "This is <b>bold</b> text"
    tag: str            # 원본 태그 이름 ("p", "h1", "li" 등)
    word_count: int     # 단어 수 (영문 기준, 청크 분할용)

@dataclass
class Chapter:
    """EPUB 내 하나의 챕터(문서)"""
    id: str             # "ch00", "ch01", ...
    title: str          # 챕터 제목 (TOC 또는 첫 heading)
    href: str           # EPUB 내부 경로 (예: "OEBPS/text/ch01.xhtml")
    content: str        # 원본 XHTML 전체 (재조립 시 사용)
    text_blocks: list[TextBlock] = field(default_factory=list)
```

### 데이터 클래스 (`src/chunker.py`)

```python
from dataclasses import dataclass, field

@dataclass
class Chunk:
    """번역 단위 — 1개 이상의 TextBlock 묶음"""
    id: str             # "ch01_chunk00", "ch01_chunk01", ...
    chapter_id: str     # 소속 챕터 ID
    text: str           # 번역할 텍스트 (문단 간 \n\n 구분)
    context: str        # 이전 컨텍스트 (직전 2문장, 번역 일관성용)
    block_indices: list[int] = field(default_factory=list)
                        # 이 청크에 포함된 TextBlock의 index 목록
```

### `src/epub_parser.py`

```python
def parse_epub(epub_path: str) -> list[Chapter]:
    """
    EPUB 파일을 파싱하여 챕터 리스트를 반환한다.

    처리 순서:
    1. EbookLib으로 EPUB 로드
    2. spine 순서대로 문서(item) 순회
    3. 각 문서의 XHTML을 BeautifulSoup로 파싱
    4. 번역 대상 블록 요소(p, h1-h6, li, blockquote, figcaption) 추출
    5. script, style, nav 내부 텍스트는 제외
    6. 빈 블록(공백만 있는)은 제외

    Args:
        epub_path: EPUB 파일 경로
    Returns:
        spine 순서대로 정렬된 Chapter 리스트
    """
    ...
```

### `src/chunker.py`

```python
def chunk_chapter(chapter: Chapter, max_words: int = 800) -> list[Chunk]:
    """
    챕터의 TextBlock들을 max_words 이하의 Chunk로 분할한다.

    분할 규칙:
    1. TextBlock을 순서대로 누적하며 word_count 합산
    2. 누적 합이 max_words를 초과하면 현재까지를 하나의 Chunk로 확정
    3. 단일 TextBlock이 max_words 초과 시 → 그 블록만으로 1개 Chunk
    4. 각 Chunk에 이전 Chunk 마지막 2문장을 context로 첨부

    Args:
        chapter: 파싱된 Chapter 객체
        max_words: 청크당 최대 단어 수 (기본 800)
    Returns:
        Chunk 리스트 (챕터 내 순서 보장)
    """
    ...


def _extract_last_sentences(text: str, n: int = 2) -> str:
    """텍스트에서 마지막 n개 문장을 추출한다 (컨텍스트용)."""
    ...
```

### `src/translator.py`

```python
SYSTEM_PROMPT = """You are a professional English-to-Korean book translator.

Rules:
1. Translate accurately while maintaining natural Korean flow
2. Preserve all HTML tags exactly as they appear (<b>, <i>, <a>, etc.)
3. Keep proper nouns (person names, place names) in their original English form
4. Maintain the same number of paragraphs as the input — use blank lines between paragraphs
5. Output ONLY the Korean translation — no explanations, notes, or commentary
6. For technical terms, use the common Korean translation with the original in parentheses on first occurrence"""

USER_PROMPT_TEMPLATE = """/no_think

{context_block}Translate the following English text to Korean.
Each paragraph is separated by a blank line. Preserve the same paragraph structure.

[TEXT]
{chunk_text}
[/TEXT]"""

# context_block은 컨텍스트가 있을 때만 포함:
CONTEXT_BLOCK_TEMPLATE = """[CONTEXT — for reference only, do NOT translate this]
{context}
[/CONTEXT]

"""


def translate_chunk(
    chunk: Chunk,
    model: str = "mlx-community/Qwen3.5-35B-A3B-4bit",
    endpoint: str = "http://localhost:8080/v1",
    temperature: float = 0.1,
    top_p: float = 0.3,
    max_tokens: int = 4096,
    max_retries: int = 3,
) -> str:
    """
    하나의 Chunk를 MLX-LM API로 번역한다.

    처리:
    1. SYSTEM_PROMPT + USER_PROMPT_TEMPLATE로 메시지 구성
    2. OpenAI 호환 API 호출
    3. 실패 시 exponential backoff로 재시도 (1s, 2s, 4s)
    4. 빈 응답 시 1회 재시도
    5. max_retries 초과 시 예외 발생

    Args:
        chunk: 번역할 Chunk 객체
        model: MLX-LM 모델 이름
        endpoint: MLX-LM 서버 URL
        temperature: 샘플링 온도 (낮을수록 결정적)
        top_p: nucleus sampling 임계값
        max_tokens: 최대 생성 토큰 수
        max_retries: 최대 재시도 횟수
    Returns:
        번역된 한국어 텍스트
    Raises:
        TranslationError: 모든 재시도 실패 시
    """
    ...


class TranslationError(Exception):
    """번역 실패 예외"""
    def __init__(self, chunk_id: str, message: str, retry_count: int):
        self.chunk_id = chunk_id
        self.retry_count = retry_count
        super().__init__(f"Chunk {chunk_id}: {message} (retries: {retry_count})")
```

### `src/epub_builder.py`

```python
def build_epub(
    original_path: str,
    translated_chapters: dict[str, dict[int, str]],
    output_path: str,
) -> None:
    """
    원본 EPUB의 구조를 유지하면서 번역된 텍스트로 교체한 새 EPUB을 생성한다.

    처리:
    1. EbookLib으로 원본 EPUB 로드
    2. 각 챕터의 XHTML을 BeautifulSoup로 파싱
    3. 블록 요소를 순서대로 순회하며 번역문으로 교체
    4. dc:language 메타데이터를 'ko'로 변경
    5. 이미지, CSS, 폰트 등 비텍스트 자원은 그대로 복사
    6. 새 EPUB 파일로 저장

    Args:
        original_path: 원본 EPUB 파일 경로
        translated_chapters: {chapter_id: {block_index: translated_html}}
        output_path: 출력 EPUB 파일 경로
    """
    ...
```

### `src/checkpoint.py`

```python
def save_progress(checkpoint_path: str, data: dict) -> None:
    """
    체크포인트 데이터를 atomic write로 저장한다.

    Atomic write: tempfile에 먼저 쓴 후 os.replace()로 원자적 치환.
    → 쓰기 중 크래시해도 기존 체크포인트가 손상되지 않음.

    Args:
        checkpoint_path: 체크포인트 JSON 파일 경로
        data: 체크포인트 딕셔너리 (아래 구조 참조)
    """
    ...


def load_progress(checkpoint_path: str) -> dict | None:
    """
    체크포인트 파일을 로드한다.

    Args:
        checkpoint_path: 체크포인트 JSON 파일 경로
    Returns:
        체크포인트 딕셔너리. 파일 없으면 None.
    """
    ...
```

### `translate.py` (CLI 진입점)

```python
def run_pipeline(
    input_path: str,
    output_path: str,
    model: str,
    checkpoint_path: str,
    resume: bool,
    max_words: int,
) -> None:
    """
    번역 파이프라인 메인 루프.

    1. parse_epub() → chapters
    2. 각 chapter에 대해 chunk_chapter() → chunks
    3. checkpoint 로드 (resume=True일 때)
    4. 각 chunk에 대해:
       a. 이미 완료된 청크면 스킵
       b. translate_chunk() 호출
       c. 결과를 checkpoint에 저장
       d. tqdm 진행률 업데이트
    5. build_epub() → 출력 파일 생성
    """
    ...


def main():
    """CLI 인터페이스 — argparse 설정 및 run_pipeline 호출."""
    ...
```

---

## CLI 인터페이스

```
usage: translate.py [-h] [--output OUTPUT] [--model MODEL]
                    [--checkpoint CHECKPOINT] [--resume]
                    [--max-words MAX_WORDS]
                    input

킨들 영문 EPUB을 한국어로 번역합니다.

positional arguments:
  input                 입력 EPUB 파일 경로

optional arguments:
  -h, --help            도움말
  --output OUTPUT       출력 EPUB 경로 (기본: input_kr.epub)
  --model MODEL         MLX-LM 모델 이름
                        (기본: mlx-community/Qwen3.5-35B-A3B-4bit)
  --checkpoint CHECKPOINT
                        체크포인트 파일 경로
                        (기본: checkpoints/{input_stem}_progress.json)
  --resume              기존 체크포인트에서 이어하기
  --max-words MAX_WORDS 청크당 최대 단어 수 (기본: 800)
```

### 사용 예시

```bash
# 기본 사용
python3 translate.py mybook.epub

# 출력 파일 지정
python3 translate.py mybook.epub --output mybook_korean.epub

# 중단 후 재시작
python3 translate.py mybook.epub --resume

# 다른 모델 사용
python3 translate.py mybook.epub --model "mlx-community/Qwen3-30B-A3B-4bit"
```

---

## 체크포인트 JSON 구조

```json
{
  "source": "mybook.epub",
  "model": "mlx-community/Qwen3.5-35B-A3B-4bit",
  "started_at": "2026-03-29T14:30:00",
  "updated_at": "2026-03-29T15:45:00",
  "total_chunks": 120,
  "completed_chunks": 45,
  "failed_chunks": 3,
  "chapters": {
    "ch00": {
      "title": "Preface",
      "total_blocks": 12,
      "status": "done"
    },
    "ch01": {
      "title": "Chapter 1",
      "total_blocks": 45,
      "status": "in_progress"
    }
  },
  "chunks": {
    "ch00_chunk00": {
      "status": "done",
      "block_indices": [0, 1, 2, 3],
      "translated": "번역된 문단1\n\n번역된 문단2\n\n..."
    },
    "ch01_chunk00": {
      "status": "done",
      "block_indices": [0, 1, 2],
      "translated": "..."
    },
    "ch01_chunk01": {
      "status": "failed",
      "block_indices": [3, 4, 5],
      "error": "timeout",
      "retry_count": 3
    },
    "ch01_chunk02": {
      "status": "pending",
      "block_indices": [6, 7]
    }
  }
}
```

### 상태 전이

```
pending → done      (번역 성공)
pending → failed    (max_retries 초과)
failed  → done      (--resume로 재시도 성공)
```

### 체크포인트 저장 시점

- 매 청크 번역 완료 후 즉시 저장 (atomic write)
- 전체 파이프라인 시작 시 초기 체크포인트 생성
- `--resume` 시 기존 체크포인트 로드 → `pending`/`failed` 청크만 재시도

---

## 번역 프롬프트 (최종 확정)

### System Prompt

```
You are a professional English-to-Korean book translator.

Rules:
1. Translate accurately while maintaining natural Korean flow
2. Preserve all HTML tags exactly as they appear (<b>, <i>, <a>, etc.)
3. Keep proper nouns (person names, place names) in their original English form
4. Maintain the same number of paragraphs as the input — use blank lines between paragraphs
5. Output ONLY the Korean translation — no explanations, notes, or commentary
6. For technical terms, use the common Korean translation with the original in parentheses on first occurrence
```

### User Prompt 템플릿

컨텍스트가 있는 경우:
```
/no_think

[CONTEXT — for reference only, do NOT translate this]
{이전 청크의 마지막 2문장}
[/CONTEXT]

Translate the following English text to Korean.
Each paragraph is separated by a blank line. Preserve the same paragraph structure.

[TEXT]
{번역할 청크 텍스트 — HTML 인라인 태그 포함}
[/TEXT]
```

첫 번째 청크 (컨텍스트 없음):
```
/no_think

Translate the following English text to Korean.
Each paragraph is separated by a blank line. Preserve the same paragraph structure.

[TEXT]
{번역할 청크 텍스트}
[/TEXT]
```

### Qwen3 Thinking 모드 비활성화

- **방법**: User prompt 첫 줄에 `/no_think` 토큰 삽입
- **원리**: Qwen3 chat template이 `/no_think`을 감지하면 thinking block을 생략
- **효과**: 불필요한 reasoning 토큰 제거 → 번역 속도 2-3배 향상, 출력 품질 유지
- **대안 (fallback)**: MLX-LM이 `/no_think`을 지원하지 않을 경우 `extra_body={"enable_thinking": false}` 시도

### 샘플링 파라미터

```python
{
    "temperature": 0.1,     # 낮은 값 → 결정적 출력 (번역 정확도 우선)
    "top_p": 0.3,           # 좁은 확률 분포 → 안정적 번역
    "max_tokens": 4096,     # 원문의 ~2배 (한국어가 영어보다 짧지만 여유 확보)
}
```

> **참고**: `repetition_penalty`는 OpenAI 호환 API 표준에 포함되지 않음.
> MLX-LM이 지원하면 `1.1` 추가 권장 (반복 방지). 미지원 시 생략.

---

## 에러 처리

### 1. API 호출 실패 (타임아웃 / 네트워크)

```python
def translate_with_retry(chunk, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = call_api(chunk)
            if not result.strip():
                raise EmptyResponseError()
            return result
        except (TimeoutError, ConnectionError, EmptyResponseError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                time.sleep(wait)
            else:
                # 체크포인트에 failed로 기록하고 다음 청크로 진행
                return None  # 파이프라인에서 처리
```

**전략**: 실패한 청크는 `status: "failed"`로 기록 → `--resume`으로 나중에 재시도.
전체 파이프라인을 중단하지 않고 계속 진행한다.

### 2. 빈 응답 처리

- LLM이 빈 문자열 반환 시 → 즉시 1회 재시도 (같은 프롬프트)
- 2회 연속 빈 응답 → `failed`로 기록

### 3. 문단 수 불일치

번역 결과의 `\n\n` 분할 개수가 원본 블록 수와 다를 때:
- **블록이 1개인 경우**: 전체 번역문을 그대로 사용 (분할 불필요)
- **블록이 여러 개인데 분할 수가 다른 경우**: 전체 번역문을 첫 번째 블록에 합쳐서 배치
- 로그 경고 출력 (`WARNING: Paragraph count mismatch in {chunk_id}`)

### 4. 긴 청크 (max_tokens 초과 응답)

- LLM 응답이 `finish_reason: "length"`인 경우 → 응답이 잘린 것
- **처리**: 해당 청크를 `failed`로 기록, `--resume` 시 `max_words`를 절반으로 줄여 재분할 시도
- 초기 구현에서는 수동 처리 안내 (`WARNING: Chunk {id} response truncated`)

### 5. EPUB 파싱 실패

- 지원하지 않는 EPUB 형식 (DRM 등) → 즉시 종료 + 에러 메시지
- 개별 챕터 파싱 실패 → 해당 챕터 스킵 + 경고 로그

### 6. MLX-LM 서버 미실행

- 파이프라인 시작 전 `http://localhost:8080/v1/models` 엔드포인트로 연결 확인
- 실패 시 안내 메시지 출력 후 종료:
  ```
  ERROR: MLX-LM 서버에 연결할 수 없습니다.
  서버를 먼저 시작하세요: mlx_lm.server --model mlx-community/Qwen3.5-35B-A3B-4bit --port 8080
  ```

---

## 구현 순서 (Developer 가이드)

### Step 1: 프로젝트 기반 설정

**파일**: `src/__init__.py`, `tests/__init__.py`, `requirements.txt`

- `__init__.py` 빈 파일 생성
- 의존성 정의:
  ```
  ebooklib>=0.18
  beautifulsoup4>=4.12
  openai>=1.0
  tqdm>=4.60
  ```

### Step 2: 체크포인트 모듈

**파일**: `src/checkpoint.py`, `tests/test_checkpoint.py`

- `save_progress()`: tempfile + os.replace atomic write
- `load_progress()`: JSON 로드, 파일 없으면 None
- 테스트: 저장/로드 왕복, 파일 없는 경우, 잘못된 JSON 처리

**이유**: 다른 모듈과 의존성 없음. 가장 단순하고 독립적.

### Step 3: EPUB 파서

**파일**: `src/epub_parser.py`, `tests/test_epub_parser.py`

- `parse_epub()`: EbookLib 로드 → spine 순회 → BeautifulSoup로 블록 추출
- 번역 대상 태그: `p, h1, h2, h3, h4, h5, h6, li, blockquote, figcaption`
- 제외: `script, style, nav` 내부, 빈 블록
- TextBlock.text는 블록의 **inner HTML** (인라인 태그 보존)
- 테스트: 샘플 EPUB으로 파싱 결과 검증

### Step 4: 청크 분할

**파일**: `src/chunker.py`, `tests/test_chunker.py`

- `chunk_chapter()`: TextBlock 순회, word_count 누적, max_words 기준 분할
- `_extract_last_sentences()`: 마지막 2문장 추출 (컨텍스트용)
- Chunk.text: 블록 텍스트들을 `\n\n`으로 결합
- 테스트: 경계 케이스 (빈 챕터, 단일 긴 블록, 여러 짧은 블록)

### Step 5: 번역기

**파일**: `src/translator.py`, `tests/test_translator.py`

- `translate_chunk()`: OpenAI 클라이언트로 API 호출
- 프롬프트 조립: SYSTEM_PROMPT + USER_PROMPT_TEMPLATE
- exponential backoff 재시도 로직
- TranslationError 예외 클래스
- 테스트: mock API 응답으로 정상/실패/빈응답 시나리오

### Step 6: EPUB 빌더

**파일**: `src/epub_builder.py`, `tests/test_epub_builder.py`

- `build_epub()`: 원본 EPUB 로드 → 챕터별 XHTML 수정 → 저장
- BeautifulSoup로 블록 요소 순회, 번역문으로 inner HTML 교체
- `dc:language` 메타데이터 변경
- 이미지/CSS/폰트는 원본 그대로 복사
- 테스트: 원본 vs 번역본 구조 비교, 메타데이터 확인

### Step 7: CLI + 파이프라인 통합

**파일**: `translate.py`

- argparse 설정
- `run_pipeline()`: 전체 흐름 오케스트레이션
- tqdm 진행률 표시
- 서버 연결 확인 (시작 전 health check)
- 최종 통계 출력 (완료/실패/스킵 청크 수, 소요 시간)

### Step 8: End-to-End 테스트

- 실제 EPUB 파일로 전체 파이프라인 실행
- 출력 EPUB를 EPUB 뷰어(Calibre 등)에서 확인
- 체크포인트 중단/재시작 시나리오 검증

---

## 설계 결정 근거

### 1. 순차 처리 vs 병렬 처리

**선택**: 순차 처리 (ThreadPoolExecutor 미사용)

**이유**:
- MLX-LM 서버가 단일 GPU 인스턴스 → 동시 요청이 실제로는 직렬 처리됨
- 병렬 처리 시 체크포인트 race condition 발생 → Lock 또는 개별 파일 필요
- 복잡도 대비 성능 이득이 미미
- 번역 품질 디버깅이 순차 방식에서 훨씬 용이
- **향후**: 서버가 배치 처리 지원하면 그때 병렬화 추가

### 2. Atomic Write 체크포인트

**선택**: tempfile + os.replace() 방식

**대안**: threading.Lock, 청크별 개별 파일

**이유**:
- 순차 처리이므로 Lock 불필요
- 개별 파일은 관리 복잡성 증가 (수백 개 파일)
- os.replace()는 OS 레벨 원자적 연산 → 쓰기 중 크래시에도 안전

### 3. 문단 단위 inner HTML 번역

**선택**: 블록 요소의 inner HTML을 통째로 번역 (인라인 태그 포함)

**대안 A**: 텍스트 노드만 개별 번역 → 컨텍스트 손실
**대안 B**: 플레이스홀더 치환 (`<b>text</b>` → `{{1}}text{{/1}}`) → 과잉 설계

**이유**:
- LLM이 HTML 태그를 잘 보존하는 것으로 알려져 있음 (프롬프트에서 명시적 지시)
- 컨텍스트가 충분해야 자연스러운 번역 가능
- 문제 발생 시 플레이스홀더 방식으로 전환 가능 (하위 호환)

### 4. `/no_think` 프롬프트 방식

**선택**: User prompt 첫 줄에 `/no_think` 삽입

**대안**: API 파라미터 `enable_thinking=false`

**이유**:
- Qwen3 tokenizer가 `/no_think`을 직접 인식 → 가장 확실한 방법
- MLX-LM의 OpenAI 호환 API가 `enable_thinking` 파라미터를 지원하는지 불확실
- 프롬프트 방식은 서버 구현에 독립적

### 5. 번역 실패 시 계속 진행

**선택**: 실패한 청크를 `failed`로 기록하고 다음 청크로 계속

**대안**: 실패 시 전체 중단

**이유**:
- 긴 책은 번역에 수 시간 소요 → 중간 실패로 전체 중단은 비효율적
- `--resume`으로 실패한 부분만 재시도 가능
- 최종 빌드 시 실패 청크는 원문 유지 (부분 번역이라도 유용)
