"""Anthropic adapter — Claude models with thinking mode support."""
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

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicAdapter(BaseLLMAdapter):
    """Adapter for Anthropic Claude API.

    Supports extended thinking mode and prompt caching.
    Uses httpx directly (no anthropic SDK dependency).
    """

    def __init__(self, config: LlmConfig) -> None:
        super().__init__(config)
        self._base_url = (config.base_url or ANTHROPIC_BASE_URL).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "x-api-key": self.config.api_key,
                    "anthropic-version": ANTHROPIC_API_VERSION,
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.config.timeout, connect=10.0),
            )
        return self._client

    def _build_body(self, messages: list[LlmMessage], **kwargs) -> dict:
        # Anthropic separates system from messages
        system_text = ""
        api_messages = []
        for m in messages:
            if m.role == "system":
                system_text += m.content + "\n"
            else:
                api_messages.append({"role": m.role, "content": m.content})

        body: dict = {
            "model": self.config.model_name,
            "messages": api_messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
        }

        if system_text.strip():
            body["system"] = system_text.strip()

        # Temperature
        body["temperature"] = kwargs.get("temperature", self.config.temperature)

        # Thinking mode (extended thinking for Claude 3.5+)
        if self.config.thinking_mode and self.config.supports_thinking:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": min(
                    kwargs.get("thinking_budget", 10000),
                    self.config.max_tokens - 1000,
                ),
            }
            # When thinking is enabled, temperature must be 1
            body["temperature"] = 1.0

        # Streaming
        if kwargs.get("stream"):
            body["stream"] = True

        return body

    async def _do_chat(self, messages: list[LlmMessage], **kwargs) -> LlmResponse:
        client = self._get_client()
        body = self._build_body(messages, **kwargs)

        resp = await client.post("/messages", json=body)
        resp.raise_for_status()
        data = resp.json()

        # Extract text from content blocks
        text_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "thinking":
                # Include thinking in a special format for debugging
                pass  # Skip thinking blocks in output text

        usage_data = data.get("usage", {})

        return LlmResponse(
            text="".join(text_parts),
            usage=LlmUsage(
                prompt_tokens=usage_data.get("input_tokens", 0),
                completion_tokens=usage_data.get("output_tokens", 0),
                total_tokens=(
                    usage_data.get("input_tokens", 0)
                    + usage_data.get("output_tokens", 0)
                ),
            ),
            finish_reason=data.get("stop_reason", "end_turn"),
            model=data.get("model", self.config.model_name),
        )

    async def _do_stream(self, messages: list[LlmMessage],
                         **kwargs) -> AsyncIterator[LlmDelta]:
        client = self._get_client()
        body = self._build_body(messages, stream=True, **kwargs)

        async with client.stream("POST", "/messages", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]

                import json
                try:
                    event = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    continue

                event_type = event.get("type")

                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield LlmDelta(text=delta.get("text", ""))

                elif event_type == "message_delta":
                    usage = event.get("usage", {})
                    yield LlmDelta(
                        text="",
                        finish_reason=event.get("delta", {}).get("stop_reason", "end_turn"),
                        usage=LlmUsage(
                            prompt_tokens=0,
                            completion_tokens=usage.get("output_tokens", 0),
                            total_tokens=usage.get("output_tokens", 0),
                        ),
                    )

                elif event_type == "message_stop":
                    break

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
