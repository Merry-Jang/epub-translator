"""LLM 프로바이더 추상화 — Local MLX-LM / OpenAI / Anthropic Claude."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

Provider = Literal["local", "openai", "claude", "gemini"]

DEFAULT_MODELS: dict[str, str] = {
    "local": "mlx-community/Qwen3.5-35B-A3B-4bit",
    "openai": "gpt-4o-mini",
    "claude": "claude-3-5-haiku-20241022",
    "gemini": "gemini-2.5-flash",
}


@dataclass
class CompletionResult:
    content: str
    finish_reason: str  # "stop" | "length"


class LLMClient:
    """OpenAI / Anthropic / Local LLM 통합 클라이언트.

    Usage:
        client = LLMClient("local")
        client = LLMClient("openai", api_key="sk-...")
        client = LLMClient("claude", api_key="sk-ant-...")
    """

    def __init__(
        self,
        provider: Provider,
        api_key: str | None = None,
        endpoint: str | None = None,
    ):
        self.provider = provider
        self._openai_client = None
        self._anthropic_client = None

        if provider in ("local", "openai", "gemini"):
            from openai import OpenAI
            kwargs: dict = {}
            if provider == "local":
                kwargs["api_key"] = api_key or "not-needed"
                kwargs["base_url"] = endpoint or "http://localhost:8080/v1"
            elif provider == "gemini":
                # Gemini OpenAI 호환 API 사용
                import os
                kwargs["api_key"] = api_key or os.environ.get("GEMINI_API_KEY", "")
                kwargs["base_url"] = endpoint or "https://generativelanguage.googleapis.com/v1beta/openai/"
            else:
                # openai — api_key None이면 OPENAI_API_KEY 환경변수 자동 사용
                if api_key:
                    kwargs["api_key"] = api_key
                if endpoint:
                    kwargs["base_url"] = endpoint
            self._openai_client = OpenAI(**kwargs)

        elif provider == "claude":
            from anthropic import Anthropic
            # api_key None이면 ANTHROPIC_API_KEY 환경변수 자동 사용
            kwargs = {}
            if api_key:
                kwargs["api_key"] = api_key
            self._anthropic_client = Anthropic(**kwargs)

        else:
            raise ValueError(f"지원하지 않는 프로바이더: {provider!r}. (local / openai / claude / gemini)")

    def complete(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        top_p: float = 0.3,
    ) -> CompletionResult:
        """통합 완성 메서드."""
        if self.provider in ("local", "openai", "gemini"):
            return self._complete_openai(messages, model, max_tokens, temperature, top_p)
        else:
            return self._complete_anthropic(messages, model, max_tokens, temperature, top_p)

    def _complete_openai(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> CompletionResult:
        response = self._openai_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=False,
        )
        content = response.choices[0].message.content or ""
        finish_reason = response.choices[0].finish_reason or "stop"
        return CompletionResult(content=content, finish_reason=finish_reason)

    def _complete_anthropic(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> CompletionResult:
        # Anthropic API는 system 메시지를 별도 파라미터로 전달
        system = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                user_messages.append(msg)

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": user_messages,
            "temperature": temperature,
            "top_p": top_p,
        }
        if system:
            kwargs["system"] = system

        response = self._anthropic_client.messages.create(**kwargs)
        content = response.content[0].text if response.content else ""
        finish_reason = "length" if response.stop_reason == "max_tokens" else "stop"
        return CompletionResult(content=content, finish_reason=finish_reason)

    def check_connection(self) -> bool:
        """Local 프로바이더 서버 연결 확인 (cloud 프로바이더는 항상 True)."""
        if self.provider != "local":
            return True
        import httpx
        base_url = self._openai_client.base_url
        try:
            resp = httpx.get(f"{base_url}models", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False
