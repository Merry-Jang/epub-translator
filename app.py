#!/usr/bin/env python3
"""킨들 영문 EPUB 번역기 — Gradio 웹 UI."""

import logging
import os
import tempfile
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
    if epub_file is None:
        return None, "EPUB 파일을 업로드하세요."

    model = model_name.strip() or DEFAULT_MODELS[provider]
    ep = endpoint.strip() or None
    key = api_key.strip() or None

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
            f"python3 -m mlx_lm.server --model {model} --port 8080"
        )

    # 출력 경로 — temp 디렉토리에 저장 (Gradio 다운로드용)
    stem = Path(epub_file).stem
    output_dir = tempfile.mkdtemp()
    output_path = os.path.join(output_dir, f"{stem}_kr.epub")
    checkpoint_path = f"checkpoints/{stem}_progress.json"

    try:
        logger.info("번역 시작 — 프로바이더: %s / 모델: %s", provider, model)
        run_pipeline(
            input_path=epub_file,
            output_path=output_path,
            model=model,
            checkpoint_path=checkpoint_path,
            resume=resume,
            max_words=max_words,
            client=client,
        )
        return output_path, f"번역 완료!\n모델: {model}\n출력: {Path(output_path).name}"

    except Exception as e:
        logger.exception("번역 실패")
        return None, f"번역 실패: {e}"


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
                    info="중단된 번역을 체크포인트에서 재개",
                )

            translate_btn = gr.Button("번역 시작", variant="primary", size="lg")

        # 오른쪽: 결과
        with gr.Column(scale=1):
            status = gr.Textbox(
                label="상태",
                interactive=False,
                lines=5,
                placeholder="번역 완료 후 여기에 결과가 표시됩니다.",
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
python3 -m mlx_lm.server --model mlx-community/Qwen3.5-35B-A3B-4bit --port 8080
```
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
