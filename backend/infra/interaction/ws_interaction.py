"""InteractionPort implementation — collects user responses via WebSocket."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog

from ports.interaction_port import PromptCtx, Choice

log = structlog.get_logger()

DEFAULT_TIMEOUT = 300


class WsInteraction:
    """Implements InteractionPort by sending prompt.request over WS
    and awaiting prompt.response with matching request_id."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._broadcast_fn = None

    def set_broadcast(self, fn) -> None:
        self._broadcast_fn = fn

    def resolve(self, request_id: str, response: dict) -> None:
        fut = self._pending.get(request_id)
        if fut and not fut.done():
            fut.set_result(response)

    async def prompt_choice(self, ctx: PromptCtx, options: list[Choice]) -> str:
        request_id = ctx.request_id or uuid.uuid4().hex[:12]
        response = await self._send_and_wait(request_id, {
            "project_id": ctx.project_id,
            "task_id": ctx.task_id,
            "title": ctx.title,
            "type": "choice",
            "options": [{"value": o.value, "label": o.label} for o in options],
        })
        return response.get("value", options[0].value if options else "")

    async def prompt_text(self, ctx: PromptCtx, hint: str = "") -> str:
        request_id = ctx.request_id or uuid.uuid4().hex[:12]
        response = await self._send_and_wait(request_id, {
            "project_id": ctx.project_id,
            "task_id": ctx.task_id,
            "title": ctx.title,
            "type": "text",
            "hint": hint,
        })
        return response.get("value", "")

    async def prompt_confirm(self, ctx: PromptCtx) -> bool:
        request_id = ctx.request_id or uuid.uuid4().hex[:12]
        response = await self._send_and_wait(request_id, {
            "project_id": ctx.project_id,
            "task_id": ctx.task_id,
            "title": ctx.title,
            "type": "confirm",
        })
        return response.get("value") in (True, "true", "yes", "1")

    async def _send_and_wait(self, request_id: str,
                              payload: dict[str, Any]) -> dict:
        if not self._broadcast_fn:
            raise RuntimeError("WsInteraction not connected to broadcast")

        fut: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut

        await self._broadcast_fn("prompt.request", {
            "request_id": request_id,
            **payload,
        })

        try:
            return await asyncio.wait_for(fut, timeout=DEFAULT_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning("ws_interaction.timeout", request_id=request_id)
            return {}
        finally:
            self._pending.pop(request_id, None)


ws_interaction = WsInteraction()
