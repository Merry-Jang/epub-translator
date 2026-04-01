# 킨들 영문 EPUB 번역기

개인 구매한 영문 EPUB을 한국어로 번역하는 로컬 도구입니다.
MLX-LM(로컬 무료) 또는 OpenAI / Claude API를 선택할 수 있습니다.

---

## 빠른 시작 (원클릭)

```bash
# 1. 저장소 클론
git clone https://github.com/Merry-Jang/kindle-translator.git
cd kindle-translator

# 2. 설치 (최초 1회)
./install.sh

# 3. 실행
./run.sh
```

브라우저에서 http://localhost:7860 이 자동으로 열립니다.

---

## 번역 엔진 선택

| 엔진 | 특징 | 사전 준비 |
|------|------|-----------|
| **local** | 무료, 빠름 (M1/M2/M3 Mac 전용) | MLX-LM 서버 실행 필요 |
| **openai** | 유료, 간편 | OpenAI API 키 |
| **claude** | 유료, 한국어 품질 우수 | Anthropic API 키 |

### 로컬 MLX-LM 서버 시작 (local 엔진 사용 시)

```bash
# 별도 터미널에서 실행
./venv/bin/python3 -m mlx_lm.server \
    --model mlx-community/Qwen3.5-35B-A3B-4bit \
    --port 8080
```

> 첫 실행 시 모델 다운로드(~20GB)가 진행됩니다.

---

## 사용 방법

1. `./run.sh` 실행 → 브라우저에서 UI 열림
2. EPUB 파일을 드래그 앤 드롭
3. 번역 엔진 선택 (openai/claude 선택 시 API 키 입력)
4. **번역 시작** 클릭
5. 완료 후 번역본 다운로드

---

## CLI 직접 사용 (고급)

```bash
# 로컬 MLX-LM
./venv/bin/python3 translate.py book.epub

# OpenAI
./venv/bin/python3 translate.py book.epub --provider openai --api-key sk-...

# Claude
./venv/bin/python3 translate.py book.epub --provider claude --api-key sk-ant-...

# 중단 후 이어서
./venv/bin/python3 translate.py book.epub --resume
```

---

## 시스템 요구사항

- macOS (Apple Silicon 권장)
- Python 3.10 이상
- EPUB 파일 (DRM 해제된 파일)

> Kindle 파일(.azw3)은 Calibre + DeDRM 플러그인으로 EPUB 변환 후 사용하세요.

---

## 주의사항

- 개인 소장용 도서의 번역에만 사용하세요.
- DRM이 걸린 파일은 직접 처리할 수 없습니다.
