"""Base types and abstract adapter for LLM infrastructure."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

import structlog

log = structlog.get_logger()

# ── Data types ─────────────────────────────────────────────


@dataclass
class LlmConfig:
    """Configuration for an LLM adapter instance."""
    provider_type: str  # openai | anthropic | deepseek | qwen | gemini | ollama | custom
    api_key: str = ""
    base_url: str | None = None
    model_name: str = ""
    max_tokens: int = 4096
    supports_thinking: bool = False
    thinking_mode: bool = False  # whether to enable thinking for this call
    temperature: float = 0.7
    timeout: float = 120.0


@dataclass
class LlmMessage:
    """A single message in a conversation."""
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LlmUsage:
    """Token usage information."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LlmResponse:
    """Complete response from an LLM call."""
    text: str = ""
    usage: LlmUsage = field(default_factory=LlmUsage)
    finish_reason: str = "stop"
    model: str = ""


@dataclass
class LlmDelta:
    """A streaming chunk from an LLM call."""
    text: str = ""
    finish_reason: str | None = None
    usage: LlmUsage | None = None


# ── Abstract base adapter ──────────────────────────────────


class BaseLLMAdapter(ABC):
    """Abstract base class for LLM provider adapters.

    Provides common retry logic and timeout handling.
    Subclasses implement _do_chat and _do_stream.
    """

    def __init__(self, config: LlmConfig) -> None:
        self.config = config
        self._max_retries = 3
        self._retry_base_delay = 1.0

    async def chat(self, messages: list[LlmMessage], **kwargs) -> LlmResponse:
        """Send a chat completion request with retry logic."""
        for attempt in range(self._max_retries):
            try:
                return await asyncio.wait_for(
                    self._do_chat(messages, **kwargs),
                    timeout=self.config.timeout,
                )
            except asyncio.TimeoutError:
                log.warning("llm.timeout", attempt=attempt + 1,
                            model=self.config.model_name)
                if attempt == self._max_retries - 1:
                    raise
            except Exception as exc:
                if self._is_retryable(exc) and attempt < self._max_retries - 1:
                    delay = self._retry_base_delay * (2 ** attempt)
                    log.warning("llm.retry", attempt=attempt + 1,
                                error=str(exc), delay=delay)
                    await asyncio.sleep(delay)
                else:
                    raise
        raise RuntimeError("LLM call failed after all retries")

    async def stream(self, messages: list[LlmMessage],
                     **kwargs) -> AsyncIterator[LlmDelta]:
        """Stream a chat completion response."""
        async for delta in self._do_stream(messages, **kwargs):
            yield delta

    async def chat_json(self, messages: list[LlmMessage],
                        **kwargs) -> LlmResponse:
        """Chat with JSON mode enabled (for structured output extraction)."""
        kwargs["json_mode"] = True
        return await self.chat(messages, **kwargs)

    @abstractmethod
    async def _do_chat(self, messages: list[LlmMessage],
                       **kwargs) -> LlmResponse:
        """Provider-specific chat implementation."""
        ...

    @abstractmethod
    async def _do_stream(self, messages: list[LlmMessage],
                         **kwargs) -> AsyncIterator[LlmDelta]:
        """Provider-specific streaming implementation."""
        ...

    def _is_retryable(self, exc: Exception) -> bool:
        """Check if an exception is retryable (rate limit, server error)."""
        exc_str = str(exc).lower()
        retryable_indicators = [
            "rate_limit", "rate limit", "429",
            "500", "502", "503", "overloaded",
            "connection", "timeout",
        ]
        return any(indicator in exc_str for indicator in retryable_indicators)
