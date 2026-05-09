from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = structlog.get_logger()

router = APIRouter()


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
                log.info("ws.prompt_response", request_id=msg.get("payload", {}).get("request_id"))
                # TODO Phase 4: route to InteractionPort future resolution
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
