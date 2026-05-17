"""LLM Gateway — unified entry point for all LLM calls in the application.

Resolves provider+model from DB config, creates adapter, and provides
chat/stream/chat_json methods. Caches adapters per (provider_id, model_name).
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

import structlog


# Hard ceiling on a single chat() call. If the upstream LLM hangs past
# this (typical cause: provider unreachable from this machine — e.g.
# api.anthropic.com from CN without proxy), we cancel the request and
# raise TimeoutError instead of letting the asyncio.Task wedge forever.
# Workflow execution + Plan Maker callers treat TimeoutError as
# kind="network" via the existing error-classifier heuristic.
LLM_CALL_TIMEOUT_SECONDS = 90

from infra.llm.base import (
    BaseLLMAdapter,
    LlmConfig,
    LlmDelta,
    LlmMessage,
    LlmResponse,
)
from infra.llm.registry import create_adapter
from infra.repo import crud

log = structlog.get_logger()


class LlmGateway:
    """Singleton gateway for all LLM interactions.

    Usage:
        response = await llm_gateway.chat(provider_id, model_name, messages)
        async for delta in llm_gateway.stream(provider_id, model_name, messages):
            ...
    """

    def __init__(self) -> None:
        self._adapters: dict[str, BaseLLMAdapter] = {}

    async def chat(
        self,
        provider_id: str,
        model_name: str,
        messages: list[LlmMessage],
        *,
        thinking_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        json_mode: bool = False,
    ) -> LlmResponse:
        """Send a chat completion request."""
        adapter = await self._get_or_create_adapter(
            provider_id, model_name, thinking_mode=thinking_mode
        )
        kwargs: dict = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature

        # T2 (2026-05-17): assign a call_id and broadcast richer
        # llm.call.detail events so the LogDrawer's 「LLM 调用」 tab can
        # pair request + response per call and show messages preview /
        # token use / latency without the user having to read .mycrew/
        # files manually.
        import secrets
        call_id = secrets.token_hex(6)
        call_started_at = asyncio.get_event_loop().time()

        # Backward-compat: the legacy llm.call_started / _finished /
        # _failed events stay broadcast so any old listeners (LogDrawer
        # 应用日志 tab pre-rewrite, internal dashboards, etc.) keep
        # working. The new llm.call.detail is additive.
        await self._broadcast_event("llm.call_started", {
            "provider_id": provider_id,
            "model": model_name,
            "thinking_mode": thinking_mode,
            "json_mode": json_mode,
        })
        await self._broadcast_event("llm.call.detail", {
            "call_id": call_id,
            "phase": "request",
            "provider_id": provider_id,
            "model": model_name,
            "thinking_mode": thinking_mode,
            "json_mode": json_mode,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages_preview": _preview_messages(messages),
            "messages_count": len(messages),
        })

        try:
            # Hard network-level timeout: hung LLM calls (e.g. provider
            # unreachable, DNS blackhole, TCP SYN swallowed) would
            # otherwise wedge the calling asyncio.Task forever. Wrap with
            # asyncio.wait_for so we always reclaim the task within
            # LLM_CALL_TIMEOUT_SECONDS — the cancellation propagates into
            # adapter.chat which honours it via its own httpx client.
            if json_mode:
                response = await asyncio.wait_for(
                    adapter.chat_json(messages, **kwargs),
                    timeout=LLM_CALL_TIMEOUT_SECONDS,
                )
            else:
                response = await asyncio.wait_for(
                    adapter.chat(messages, **kwargs),
                    timeout=LLM_CALL_TIMEOUT_SECONDS,
                )
        except asyncio.TimeoutError as exc:
            await self._broadcast_event("llm.call_failed", {
                "provider_id": provider_id,
                "model": model_name,
                "error": f"timeout after {LLM_CALL_TIMEOUT_SECONDS}s — "
                         "LLM provider unreachable or hung",
            })
            await self._broadcast_event("llm.call.detail", {
                "call_id": call_id,
                "phase": "error",
                "provider_id": provider_id,
                "model": model_name,
                "error": f"timeout after {LLM_CALL_TIMEOUT_SECONDS}s",
                "latency_ms": int(
                    (asyncio.get_event_loop().time() - call_started_at) * 1000
                ),
            })
            # Re-raise as a TimeoutError with a clearer message — the
            # workflow_svc error classifier picks this up as kind=network.
            raise TimeoutError(
                f"LLM provider {provider_id} did not respond within "
                f"{LLM_CALL_TIMEOUT_SECONDS}s (check network / API key / base_url)"
            ) from exc
        except Exception as exc:
            await self._broadcast_event("llm.call_failed", {
                "provider_id": provider_id,
                "model": model_name,
                "error": str(exc),
            })
            await self._broadcast_event("llm.call.detail", {
                "call_id": call_id,
                "phase": "error",
                "provider_id": provider_id,
                "model": model_name,
                "error": str(exc)[:500],
                "latency_ms": int(
                    (asyncio.get_event_loop().time() - call_started_at) * 1000
                ),
            })
            raise

        latency_ms = int(
            (asyncio.get_event_loop().time() - call_started_at) * 1000
        )
        await self._broadcast_event("llm.call_finished", {
            "provider_id": provider_id,
            "model": model_name,
            "tokens": response.usage.total_tokens if response.usage else 0,
        })
        await self._broadcast_event("llm.call.detail", {
            "call_id": call_id,
            "phase": "response",
            "provider_id": provider_id,
            "model": model_name,
            "tokens": response.usage.total_tokens if response.usage else 0,
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "latency_ms": latency_ms,
            "text_preview": _preview_text(response.text or ""),
        })
        return response

    @staticmethod
    async def _broadcast_event(event: str, payload: dict) -> None:
        try:
            # Lazy import to avoid circular dep at module load time
            from api.ws import manager
            await manager.broadcast(event, payload)
        except Exception as exc:
            log.debug("llm.event_broadcast_failed", event=event, error=str(exc))

    async def stream(
        self,
        provider_id: str,
        model_name: str,
        messages: list[LlmMessage],
        *,
        thinking_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[LlmDelta]:
        """Stream a chat completion response."""
        adapter = await self._get_or_create_adapter(
            provider_id, model_name, thinking_mode=thinking_mode
        )
        kwargs: dict = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature

        async for delta in adapter.stream(messages, **kwargs):
            yield delta

    async def check_availability(self, provider_id: str) -> bool:
        """Check if a provider is reachable (minimal token request)."""
        try:
            provider = await crud.get_by_id("llm_providers", provider_id)
            if not provider:
                return False
            models = await crud.get_all("llm_models", "provider_id = ?", (provider_id,))
            if not models:
                return False

            model = models[0]
            config = self._build_config(provider, model, thinking_mode=False)
            adapter = create_adapter(config)

            # Minimal request to check connectivity
            response = await adapter.chat(
                [LlmMessage(role="user", content="hi")],
                max_tokens=1,
            )
            return bool(response.text)
        except Exception as exc:
            log.warning("llm.availability_check_failed",
                        provider_id=provider_id, error=str(exc))
            return False

    async def shutdown(self) -> None:
        """Close all cached adapter connections."""
        for key, adapter in self._adapters.items():
            try:
                if hasattr(adapter, "close"):
                    await adapter.close()
            except Exception:
                pass
        self._adapters.clear()

    # ── Internal ───────────────────────────────────────────

    async def _get_or_create_adapter(
        self,
        provider_id: str,
        model_name: str,
        *,
        thinking_mode: bool = False,
    ) -> BaseLLMAdapter:
        cache_key = f"{provider_id}:{model_name}:{thinking_mode}"

        if cache_key in self._adapters:
            return self._adapters[cache_key]

        provider = await crud.get_by_id("llm_providers", provider_id)
        if not provider:
            raise ValueError(f"LLM provider {provider_id} not found")

        # Find the model record
        models = await crud.get_all(
            "llm_models",
            "provider_id = ? AND model_name = ?",
            (provider_id, model_name),
        )
        model = models[0] if models else None

        config = self._build_config(provider, model, thinking_mode=thinking_mode)
        adapter = create_adapter(config)
        self._adapters[cache_key] = adapter

        log.info("llm.adapter_created",
                 provider_id=provider_id, model=model_name,
                 type=config.provider_type)
        return adapter

    def _build_config(
        self,
        provider: dict,
        model: dict | None,
        *,
        thinking_mode: bool = False,
    ) -> LlmConfig:
        model_name = model["model_name"] if model else ""
        max_tokens = model.get("max_tokens", 4096) if model else 4096
        supports_thinking = bool(model.get("supports_thinking", 0)) if model else False

        return LlmConfig(
            provider_type=provider["type"],
            api_key=provider.get("api_key_ref", "") or "",
            base_url=provider.get("base_url") or None,
            model_name=model_name,
            max_tokens=max_tokens if max_tokens else 4096,
            supports_thinking=supports_thinking,
            thinking_mode=thinking_mode and supports_thinking,
        )


# ── Message preview helpers for llm.call.detail events ───────────


# Cap on each message body's preview. Big enough to capture system
# prompt + task context, small enough to keep WS frames manageable
# and the LogDrawer scroll usable. Cap == head+tail size; middle gets
# replaced by an "…[N chars]…" elision marker.
_PREVIEW_HEAD = 1500
_PREVIEW_TAIL = 500


def _preview_one(text: str) -> str:
    """Truncate a single message body. Keeps the first 1500 chars and
    the last 500, with an elision marker in between. Short messages
    pass through unchanged."""
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= _PREVIEW_HEAD + _PREVIEW_TAIL + 32:
        return text
    head = text[:_PREVIEW_HEAD]
    tail = text[-_PREVIEW_TAIL:]
    omitted = len(text) - _PREVIEW_HEAD - _PREVIEW_TAIL
    return f"{head}\n…[{omitted} chars omitted]…\n{tail}"


def _preview_messages(messages: list) -> list[dict]:
    """Format LlmMessage list for the llm.call.detail request phase.
    Each entry: {role, content} with content truncated. Defensive
    against shapes that aren't LlmMessage (dict / namedtuple)."""
    out: list[dict] = []
    for m in messages:
        role = getattr(m, "role", None)
        content = getattr(m, "content", None)
        if role is None and isinstance(m, dict):
            role = m.get("role")
            content = m.get("content")
        out.append({
            "role": str(role) if role is not None else "",
            "content": _preview_one(content if content is not None else ""),
        })
    return out


def _preview_text(text: str) -> str:
    """Format response text for the llm.call.detail response phase.
    Same head+tail elision rule. Empty / None safe."""
    return _preview_one(text or "")


# Singleton instance
llm_gateway = LlmGateway()
