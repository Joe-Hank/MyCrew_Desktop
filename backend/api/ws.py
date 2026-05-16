from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = structlog.get_logger()

router = APIRouter()


# ── WS session token (audit 2026-05-16, Top 5 #2) ─────────────────
#
# The WebSocket endpoint used to accept any client that could reach
# localhost:<port>/ws — including malicious browser tabs that can open
# cross-origin WebSocket connections (same-origin policy does not gate
# WS the way it gates fetch). An unauthenticated client could:
#   1. Subscribe to every `tool.invoked` / `agent.output` event, watching
#      tool args (paths, commands) in real time.
#   2. Send fake `prompt.response` messages to the InteractionPort, auto-
#      approving any tool gated by `requires_confirmation=True`.
#
# Mitigation: every WS handshake must present a session token that
# matches the one generated at backend startup. The Tauri shell knows
# the token (it lives at data/runtime/session.token + is printed to
# stdout where the sidecar reads it). A foreign tab has no way to read
# either, so the connection is closed with code 4401.

_SESSION_TOKEN: str | None = None


def set_session_token(token: str) -> None:
    """Called once at lifespan startup with the generated token."""
    global _SESSION_TOKEN
    _SESSION_TOKEN = token


def get_session_token() -> str:
    """Internal helper for /auth/ws_token. Returns the generated token
    or raises if startup hasn't completed yet."""
    if _SESSION_TOKEN is None:
        raise RuntimeError("session token not initialised")
    return _SESSION_TOKEN


def generate_session_token() -> str:
    """Cryptographically-secure URL-safe token (32 bytes ≈ 43 chars)."""
    return secrets.token_urlsafe(32)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        log.info("ws.connected", total=len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections = [c for c in self._connections if c is not ws]
        log.info("ws.disconnected", total=len(self._connections))

    async def broadcast(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        # Persist before fanout so the audit trail survives even if every
        # connected client is stale. Fire-and-forget; failures are caught
        # inside events_svc.record_event and never bubble out.
        try:
            from services.events_svc import record_event
            await record_event(event_type, payload or {}, actor="system")
        except Exception:
            pass  # never let audit failure stop the broadcast

        message = json.dumps({
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        })
        async with self._lock:
            stale: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self._connections.remove(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    # Token check BEFORE accept(): the spec says we may reject before
    # the handshake completes by calling .close() directly. Code 4401
    # is custom-tier (1xxx are reserved); the frontend treats it as an
    # auth failure.
    token = ws.query_params.get("token", "")
    expected = _SESSION_TOKEN
    if expected is None or not token or not secrets.compare_digest(token, expected):
        log.warning("ws.auth_rejected",
                    has_token=bool(token), token_initialised=expected is not None)
        await ws.close(code=4401)
        return
    await manager.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg_type = msg.get("type", "")
            if msg_type == "prompt.response":
                payload = msg.get("payload", {})
                request_id = payload.get("request_id", "")
                log.info("ws.prompt_response", request_id=request_id)
                from infra.interaction.ws_interaction import ws_interaction
                ws_interaction.resolve(request_id, payload)
            elif msg_type == "ping":
                await ws.send_text(json.dumps({
                    "type": "pong",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "payload": {},
                }))
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
