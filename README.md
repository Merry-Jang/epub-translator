# EPUB Translator Studio

English EPUB books translated to Korean — locally and for free.

EPUB 영문 원서를 한국어로 통째로 번역하는 오픈소스 도구입니다.
로컬 AI 모델을 사용하면 API 비용 없이 완전 무료로 번역할 수 있습니다.

---

## Features

- **로컬 AI 번역 (무료)**: Apple Silicon Mac에서 MLX-LM + Qwen3.5-35B 모델로 비용 0원
- **클라우드 API 지원**: OpenAI, Claude, Gemini 중 선택 가능
- **웹 UI**: 브라우저에서 드래그앤드롭으로 간편하게
- **CLI**: 커맨드라인으로 자동화 가능
- **7가지 문체 프리셋**: 소설, 논문, 철학, 비즈니스, 아동, 에세이, 기본
- **체크포인트 저장**: 중단해도 이어서 번역 가능
- **실시간 진행률**: 경과시간 + 남은시간 예측
- **HTML 태그 보존**: 원본 EPUB 서식 유지

---

## Quick Start

### 설치 (최초 1회)

```bash
git clone https://github.com/Merry-Jang/epub-translator.git
cd epub-translator
./install.sh
```

### 실행

```bash
./run.sh
```

브라우저에서 `http://localhost:8000` 이 자동으로 열립니다.
EPUB 파일을 업로드하고 번역을 시작하세요.

---

## 번역 엔진 선택

| 엔진 | 비용 | 품질 | 사전 준비 |
|------|------|------|-----------|
| **local (MLX-LM)** | 무료 | 99.2% 번역률 | Apple Silicon Mac + MLX-LM 서버 |
| **openai** | 유료 | 우수 | OpenAI API 키 |
| **claude** | 유료 | 우수 (한국어 강점) | Anthropic API 키 |
| **gemini** | 유료 | 양호 | Google AI API 키 |

### 로컬 MLX-LM 서버 시작 (local 엔진 사용 시)

Apple Silicon Mac (M1/M2/M3/M4)이 필요합니다.

```bash
# MLX-LM 설치 (최초 1회)
pip install mlx-lm

# 서버 시작 (별도 터미널)
python3 -m mlx_lm.server \
    --model mlx-community/Qwen3.5-35B-A3B-4bit \
    --port 8080 \
    --chat-template-args '{"enable_thinking": false}'
```

> 첫 실행 시 모델 다운로드(~20GB)가 진행됩니다. 이후에는 캐시에서 바로 로드됩니다.
>
> `--chat-template-args` 옵션은 필수입니다. 없으면 thinking 토큰이 속도를 5배 느리게 만듭니다.

### API 키 방식 (Mac이 아닌 경우)

로컬 AI 없이도 OpenAI API 키만 있으면 바로 사용 가능합니다.
웹 UI에서 엔진을 `openai`로 선택하고 API 키를 입력하세요.

---

## 사용 방법

### 웹 UI (추천)

1. `./run.sh` 실행
2. 브라우저에서 EPUB 파일 업로드
3. 번역 엔진 선택 (local / openai / claude / gemini)
4. 문체 프리셋 선택 (소설, 논문 등)
5. **번역 시작** 클릭
6. 완료 후 번역본 다운로드

### CLI (고급)

```bash
# 로컬 MLX-LM (기본)
python3 translate.py book.epub

# OpenAI
python3 translate.py book.epub --provider openai --api-key sk-...

# Claude
python3 translate.py book.epub --provider claude --api-key sk-ant-...

# Gemini
python3 translate.py book.epub --provider gemini --api-key AIza...

# 문체 지정
python3 translate.py book.epub --style novel

# 중단 후 이어서
python3 translate.py book.epub --resume

# 출력 파일 지정
python3 translate.py book.epub --output translated.epub
```

### 문체 프리셋

| 프리셋 | CLI 옵션 | 설명 |
|--------|----------|------|
| 기본 | `--style default` | 범용 번역 |
| 소설/문학 | `--style novel` | 문학적 표현, 감정/분위기 전달 |
| 과학/논문 | `--style science` | 정확한 학술 용어, 합니다체 |
| 철학/인문 | `--style philosophy` | 추상 개념의 뉘앙스 보존 |
| 비즈니스 | `--style business` | 전문적이고 명확한 톤 |
| 아동/청소년 | `--style youth` | 쉽고 재미있는 표현 |
| 에세이 | `--style essay` | 따뜻하고 대화하는 톤 |

---

## 번역 성능

Qwen3.5-35B-A3B (Apple Silicon, thinking OFF) 기준:

| 항목 | 수치 |
|------|------|
| 번역 속도 | 약 40 tok/s |
| 10만 단어 소설 | 약 20분 |
| 번역률 | 99.2% |
| HTML 태그 보존 | 100% |
| 비용 | 무료 |

---

## 시스템 요구사항

| 항목 | 최소 | 권장 |
|------|------|------|
| OS | macOS / Linux / Windows (WSL) | macOS (Apple Silicon) |
| Python | 3.10 이상 | 3.12 |
| RAM | 8GB | 32GB (로컬 AI 사용 시) |
| 디스크 | 1GB | 25GB (모델 포함) |

> 로컬 AI(MLX-LM)는 Apple Silicon Mac 전용입니다.
> Intel Mac이나 Windows에서는 OpenAI/Claude/Gemini API를 사용하세요.

---

## 무료 EPUB 다운로드

테스트용 무료 EPUB 파일을 받을 수 있는 사이트:

- [Project Gutenberg](https://www.gutenberg.org/) — 클래식 문학 70,000+ 권
- [Standard Ebooks](https://standardebooks.org/) — 고품질 편집 클래식
- [Open Library](https://openlibrary.org/) — 인터넷 아카이브 연계
- [ManyBooks](https://manybooks.net/) — 다양한 장르
- [Feedbooks](https://www.feedbooks.com/publicdomain) — Public Domain
- [Adelaide University](https://ebooks.adelaide.edu.au/) — 호주 대학 도서관
- [Loyal Books](https://www.loyalbooks.com/) — 오디오북 + EPUB

---

## 트러블슈팅

### MLX-LM 서버가 안 뜹니다
```bash
# Python 버전 확인 (3.10 이상 필요)
python3 --version

# mlx-lm 설치 확인
pip show mlx-lm

# 포트 충돌 확인
lsof -i :8080
```

### 번역이 느립니다
- `--chat-template-args '{"enable_thinking": false}'` 옵션을 확인하세요
- Thinking 모드가 켜져 있으면 5배 느려집니다

### 체크포인트에서 이어하기가 안 됩니다
- `--resume` 옵션을 사용하세요
- 체크포인트 파일은 `checkpoints/` 폴더에 저장됩니다

### EPUB이 깨져 보입니다
- DRM이 걸린 파일은 번역할 수 없습니다
- Calibre로 EPUB 변환 후 시도해보세요

---

## Contributing

버그 리포트, 기능 제안, PR 모두 환영합니다.

- **버그 리포트**: [GitHub Issues](https://github.com/Merry-Jang/epub-translator/issues)에 남겨주세요
- **기능 제안**: Issue에 `[Feature Request]` 태그로 남겨주세요
- **PR**: fork → 수정 → PR 보내주시면 리뷰하겠습니다

---

## License

MIT License — 자유롭게 사용, 수정, 배포할 수 있습니다.
