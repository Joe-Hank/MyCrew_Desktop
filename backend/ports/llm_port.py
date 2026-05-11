"""LLM Port — abstract interface for LLM adapters (dependency inversion)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol


@dataclass
class LlmMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LlmUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LlmResponse:
    text: str = ""
    usage: LlmUsage = field(default_factory=LlmUsage)
    model: str = ""
    thinking: str | None = None


class LlmPort(Protocol):
    """Abstract interface that LLM adapters must implement."""

    async def chat(
        self,
        messages: list[LlmMessage],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
        thinking_mode: bool = False,
    ) -> LlmResponse: ...

    async def stream_chat(
        self,
        messages: list[LlmMessage],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking_mode: bool = False,
    ) -> AsyncIterator[str]: ...

    async def extract_json(
        self,
        messages: list[LlmMessage],
        *,
        model: str = "",
        schema_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
