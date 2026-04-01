#!/usr/bin/env python3
"""킨들 영문 EPUB 번역기 — Gradio 웹 UI."""

import glob
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

import gradio as gr

from src.providers import LLMClient, DEFAULT_MODELS
from translate import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CHECKPOINT_DIR = "checkpoints"

# 번역 작업 상태 관리
_translation_lock = threading.Lock()
_is_translating = False
_current_file = ""


def _get_checkpoint_status() -> str:
    """체크포인트 디렉토리를 스캔하여 현재 진행 상황을 반환."""
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    files = glob.glob(os.path.join(CHECKPOINT_DIR, "*_progress.json"))
    if not files:
        return ""

    lines = []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            total = data.get("total_chunks", 0)
            done = data.get("completed_chunks", 0)
            failed = data.get("failed_chunks", 0)
            source = Path(data.get("source", "")).name
            updated = data.get("updated_at", "")[:19]
            pct = int(done / total * 100) if total > 0 else 0

            status_icon = "✅" if done == total and total > 0 else "🔄"
            lines.append(
                f"{status_icon} {source}: {done}/{total} 청크 ({pct}%)"
                + (f", 실패 {failed}" if failed else "")
                + f" — {updated}"
            )
        except Exception:
            continue

    return "\n".join(lines) if lines else ""


def check_status():
    """현재 번역 상태 + 체크포인트 상태 반환."""
    global _is_translating, _current_file

    parts = []
    if _is_translating:
        parts.append(f"⏳ 번역 진행 중: {_current_file}\n(완료될 때까지 새 번역을 시작할 수 없습니다)")

    ckpt_status = _get_checkpoint_status()
    if ckpt_status:
        parts.append(f"📋 체크포인트:\n{ckpt_status}")

    if not parts:
        return "대기 중 — EPUB 파일을 업로드하고 번역을 시작하세요."

    return "\n\n".join(parts)


def translate_epub(
    epub_file,
    provider: str,
    api_key: str,
    model_name: str,
    max_words: int,
    endpoint: str,
    resume: bool,
    progress=gr.Progress(track_tqdm=True),
):
    """번역 파이프라인 실행 — Gradio 이벤트 핸들러."""
    global _is_translating, _current_file

    if epub_file is None:
        return None, "EPUB 파일을 업로드하세요."

    # 중복 실행 방지
    if not _translation_lock.acquire(blocking=False):
        return None, f"⚠️ 이미 번역이 진행 중입니다: {_current_file}\n완료될 때까지 기다리거나, 서버를 재시작하세요 (Ctrl+C → ./run.sh)"

    try:
        _is_translating = True
        _current_file = Path(epub_file).name

        model = (model_name or "").strip() or DEFAULT_MODELS[provider]
        ep = (endpoint or "").strip() or None
        key = (api_key or "").strip() or None

        # LLMClient 초기화
        try:
            client = LLMClient(provider=provider, api_key=key, endpoint=ep)
        except Exception as e:
            return None, f"클라이언트 초기화 실패: {e}"

        # 로컬 서버 연결 확인
        if provider == "local" and not client.check_connection():
            ep_display = ep or "http://localhost:8080/v1"
            return None, (
                f"MLX-LM 서버에 연결할 수 없습니다 ({ep_display})\n\n"
                f"서버를 먼저 시작하세요:\n"
                f"~/.pyenv/versions/3.12.11/bin/python3 -m mlx_lm.server --model {model} --port 8080"
            )

        # 출력 경로
        stem = Path(epub_file).stem
        output_dir = tempfile.mkdtemp()
        output_path = os.path.join(output_dir, f"{stem}_kr.epub")
        checkpoint_path = f"{CHECKPOINT_DIR}/{stem}_progress.json"

        # 체크포인트 존재 시 자동 resume
        if os.path.exists(checkpoint_path) and not resume:
            try:
                with open(checkpoint_path, "r") as f:
                    ckpt = json.load(f)
                done = ckpt.get("completed_chunks", 0)
                total = ckpt.get("total_chunks", 0)
                if 0 < done < total:
                    resume = True
                    logger.info("기존 체크포인트 발견 (%d/%d) — 자동 이어하기", done, total)
            except Exception:
                pass

        try:
            logger.info("번역 시작 — 프로바이더: %s / 모델: %s / 이어하기: %s", provider, model, resume)
            run_pipeline(
                input_path=epub_file,
                output_path=output_path,
                model=model,
                checkpoint_path=checkpoint_path,
                resume=resume,
                max_words=max_words,
                client=client,
            )
            return output_path, f"✅ 번역 완료!\n모델: {model}\n출력: {Path(output_path).name}"

        except Exception as e:
            logger.exception("번역 실패")
            return None, f"❌ 번역 실패: {e}\n\n체크포인트가 저장되어 있으니 '이어하기'를 체크하고 다시 시작하면 이어서 됩니다."

    finally:
        _is_translating = False
        _current_file = ""
        _translation_lock.release()


def update_provider_ui(provider: str):
    """프로바이더 변경 시 API 키 / 엔드포인트 필드 가시성 업데이트."""
    show_key = provider in ("openai", "claude")
    show_endpoint = provider == "local"
    key_placeholder = {
        "openai": "sk-...",
        "claude": "sk-ant-...",
    }.get(provider, "")
    default_model = DEFAULT_MODELS[provider]
    return (
        gr.update(visible=show_key, placeholder=key_placeholder),
        gr.update(visible=show_endpoint),
        gr.update(placeholder=f"기본: {default_model}"),
    )


# ---------------------------------------------------------------------------
# UI 레이아웃
# ---------------------------------------------------------------------------

with gr.Blocks(title="킨들 번역기") as demo:
    gr.Markdown(
        """
# 킨들 영문 EPUB 번역기
개인 구매 영문 EPUB을 한국어로 번역합니다.
로컬 MLX-LM 또는 OpenAI / Claude API를 선택할 수 있습니다.
        """
    )

    with gr.Row():
        # 왼쪽: 입력 설정
        with gr.Column(scale=1):
            epub_input = gr.File(
                label="EPUB 파일 (드래그 앤 드롭)",
                file_types=[".epub"],
                type="filepath",
            )

            provider = gr.Radio(
                choices=["local", "openai", "claude"],
                value="local",
                label="번역 엔진",
                info="local = MLX-LM 로컬 서버, openai / claude = 클라우드 API",
            )

            api_key = gr.Textbox(
                label="API 키",
                placeholder="",
                type="password",
                visible=False,
                info="미입력 시 OPENAI_API_KEY / ANTHROPIC_API_KEY 환경변수 사용",
            )

            endpoint = gr.Textbox(
                label="서버 엔드포인트",
                value="http://localhost:8080/v1",
                visible=True,
                info="MLX-LM 서버 주소 (local 전용)",
            )

            model_name = gr.Textbox(
                label="모델 이름 (빈칸 = 자동)",
                placeholder=f"기본: {DEFAULT_MODELS['local']}",
            )

            with gr.Row():
                max_words = gr.Slider(
                    minimum=200,
                    maximum=2000,
                    value=800,
                    step=100,
                    label="청크 크기 (단어)",
                    info="클수록 문맥은 좋지만 느려짐",
                )
                resume = gr.Checkbox(
                    label="이어하기",
                    value=False,
                    info="중단된 번역을 체크포인트에서 재개 (자동 감지됨)",
                )

            with gr.Row():
                translate_btn = gr.Button("번역 시작", variant="primary", size="lg")
                refresh_btn = gr.Button("상태 새로고침", variant="secondary", size="lg")

        # 오른쪽: 결과
        with gr.Column(scale=1):
            status = gr.Textbox(
                label="상태",
                interactive=False,
                lines=8,
                value=check_status(),
            )
            output_file = gr.File(
                label="번역 완료 파일 다운로드",
                interactive=False,
            )

    # 프로바이더 변경 → 필드 업데이트
    provider.change(
        fn=update_provider_ui,
        inputs=[provider],
        outputs=[api_key, endpoint, model_name],
    )

    # 번역 버튼 클릭
    translate_btn.click(
        fn=translate_epub,
        inputs=[epub_input, provider, api_key, model_name, max_words, endpoint, resume],
        outputs=[output_file, status],
    )

    # 상태 새로고침 버튼
    refresh_btn.click(
        fn=check_status,
        inputs=[],
        outputs=[status],
    )

    # 5초마다 상태 자동 갱신
    timer = gr.Timer(value=5)
    timer.tick(
        fn=check_status,
        inputs=[],
        outputs=[status],
    )

    # 페이지 로드 시 상태 표시
    demo.load(
        fn=check_status,
        inputs=[],
        outputs=[status],
    )

    gr.Markdown(
        """
---
### 사용 가이드
| 엔진 | 사전 준비 | 특징 |
|------|-----------|------|
| **local** | MLX-LM 서버 실행 필요 | 무료, 빠름 (M 시리즈 Mac) |
| **openai** | OpenAI API 키 | gpt-4o-mini 기본, 유료 |
| **claude** | Anthropic API 키 | claude-3-5-haiku 기본, 유료 |

**로컬 서버 시작:**
```
~/.pyenv/versions/3.12.11/bin/python3 -m mlx_lm.server --model mlx-community/Qwen3.5-35B-A3B-4bit --port 8080
```

**새로고침해도 진행 상태가 보입니다.** 체크포인트가 자동 저장되므로 중단 후 이어하기가 가능합니다.
        """
    )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=gr.themes.Soft(),
    )
