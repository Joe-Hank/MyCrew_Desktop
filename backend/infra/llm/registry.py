"""LLM adapter registry — maps provider type to adapter class."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from infra.llm.base import BaseLLMAdapter, LlmConfig

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

# Provider type → Adapter class mapping
_ADAPTER_MAP: dict[str, type[BaseLLMAdapter]] = {}


def _ensure_registered() -> None:
    """Lazy-register adapters on first access."""
    if _ADAPTER_MAP:
        return

    from infra.llm.openai_adapter import OpenAICompatibleAdapter
    from infra.llm.anthropic_adapter import AnthropicAdapter

    # OpenAI-compatible providers
    for provider_type in ("openai", "deepseek", "qwen", "gemini", "ollama", "custom"):
        _ADAPTER_MAP[provider_type] = OpenAICompatibleAdapter

    # Anthropic
    _ADAPTER_MAP["anthropic"] = AnthropicAdapter


def get_adapter(provider_type: str) -> type[BaseLLMAdapter]:
    """Get the adapter class for a given provider type."""
    _ensure_registered()
    adapter_cls = _ADAPTER_MAP.get(provider_type)
    if not adapter_cls:
        # Fallback to OpenAI-compatible for unknown types
        from infra.llm.openai_adapter import OpenAICompatibleAdapter
        log.warning("llm.unknown_provider_type", provider_type=provider_type,
                    fallback="OpenAICompatibleAdapter")
        return OpenAICompatibleAdapter
    return adapter_cls


def create_adapter(config: LlmConfig) -> BaseLLMAdapter:
    """Create an adapter instance from config."""
    adapter_cls = get_adapter(config.provider_type)
    return adapter_cls(config)
