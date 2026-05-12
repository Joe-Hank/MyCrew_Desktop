"""OpenAI-compatible adapter — covers OpenAI, DeepSeek, Qwen, Ollama, Custom."""
from __future__ import annotations

from typing import AsyncIterator

import httpx
import structlog

from infra.llm.base import (
    BaseLLMAdapter,
    LlmConfig,
    LlmDelta,
    LlmMessage,
    LlmResponse,
    LlmUsage,
)

log = structlog.get_logger()

# Default base URLs per provider type
DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "ollama": "http://localhost:11434/v1",
}


class OpenAICompatibleAdapter(BaseLLMAdapter):
    """Adapter for all OpenAI-compatible APIs.

    Supports: openai, deepseek, qwen, gemini, ollama, custom.
    Uses httpx directly for async HTTP calls (no SDK dependency).
    """

    def __init__(self, config: LlmConfig) -> None:
        super().__init__(config)
        self._base_url = config.base_url or DEFAULT_BASE_URLS.get(
            config.provider_type, "https://api.openai.com/v1"
        )
        # Ensure no trailing slash
        self._base_url = self._base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.config.timeout, connect=10.0),
            )
        return self._client

    def _build_body(self, messages: list[LlmMessage], **kwargs) -> dict:
        body: dict = {
            "model": self.config.model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }

        # Temperature (skip for o1/o3 models that don't support it)
        model_lower = self.config.model_name.lower()
        if not any(model_lower.startswith(p) for p in ("o1", "o3")):
            body["temperature"] = kwargs.get("temperature", self.config.temperature)

        # JSON mode
        if kwargs.get("json_mode"):
            body["response_format"] = {"type": "json_object"}

        # Streaming
        if kwargs.get("stream"):
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}

        return body

    async def _do_chat(self, messages: list[LlmMessage], **kwargs) -> LlmResponse:
        client = self._get_client()
        body = self._build_body(messages, **kwargs)

        resp = await client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage_data = data.get("usage", {})

        message = choice.get("message", {})
        content = message.get("content") or ""
        # DeepSeek V4 (and other reasoning models) put their chain-of-thought
        # in `reasoning_content` and leave `content` empty when no final answer
        # is produced. We surface reasoning above the answer separated by ---.
        reasoning = message.get("reasoning_content") or ""
        if reasoning and content:
            text = f"{reasoning}\n\n---\n\n{content}"
        else:
            text = reasoning or content

        return LlmResponse(
            text=text,
            usage=LlmUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
            model=data.get("model", self.config.model_name),
        )

    async def _do_stream(self, messages: list[LlmMessage],
                         **kwargs) -> AsyncIterator[LlmDelta]:
        client = self._get_client()
        body = self._build_body(messages, stream=True, **kwargs)

        async with client.stream("POST", "/chat/completions", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break

                import json
                try:
                    chunk = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    # May be a usage-only chunk
                    usage_data = chunk.get("usage")
                    if usage_data:
                        yield LlmDelta(
                            text="",
                            finish_reason="stop",
                            usage=LlmUsage(
                                prompt_tokens=usage_data.get("prompt_tokens", 0),
                                completion_tokens=usage_data.get("completion_tokens", 0),
                                total_tokens=usage_data.get("total_tokens", 0),
                            ),
                        )
                    continue

                delta = choices[0].get("delta", {})
                finish = choices[0].get("finish_reason")
                # DeepSeek V4 streams reasoning_content first (thinking), then
                # content (final answer). Either field can be present per chunk.
                content_chunk = delta.get("content") or ""
                reasoning_chunk = delta.get("reasoning_content") or ""
                text = reasoning_chunk + content_chunk

                yield LlmDelta(text=text, finish_reason=finish)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
