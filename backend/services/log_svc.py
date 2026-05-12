"""Log service — append/query logs persisted in SQLite `logs` table.

Plan §17.5: structured JSON-line logging with ts/level/source/project_id/task_id/event/message/request_id.
The in-memory ring buffer is kept as a fast tail-cache for the WS log drawer.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

import structlog

from infra.repo import crud

_log = structlog.get_logger()

MAX_BUFFER = 2000


class LogService:
    def __init__(self) -> None:
        # Hot tail kept in memory so the log drawer doesn't hit SQLite every render
        self._buffer: deque[dict] = deque(maxlen=MAX_BUFFER)

    async def query(
        self,
        source: str | None = None,
        level: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query logs. Falls back to in-memory buffer on DB errors."""
        try:
            where_parts: list[str] = []
            params: list[Any] = []
            if source:
                where_parts.append("source = ?")
                params.append(source)
            if level:
                where_parts.append("level = ?")
                params.append(level)
            if since:
                where_parts.append("ts >= ?")
                params.append(since)
            where = " AND ".join(where_parts) if where_parts else ""
            rows = await crud.get_all("logs", where, tuple(params))
            # Most recent first, then limit
            rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
            return rows[:limit]
        except Exception as exc:
            _log.warning("log_svc.query_fallback_to_buffer", error=str(exc))
            results = list(self._buffer)
            if source:
                results = [r for r in results if r.get("source") == source]
            if level:
                results = [r for r in results if r.get("level") == level]
            if since:
                results = [r for r in results if r.get("ts", "") >= since]
            return results[-limit:]

    async def append(self, entry: dict) -> None:
        """Append a log entry. Persists to SQLite + keeps in tail buffer."""
        if "ts" not in entry:
            entry["ts"] = datetime.now(timezone.utc).isoformat()
        # Buffer first (cheap, can't fail)
        self._buffer.append(entry)
        # Persist (best-effort)
        try:
            await crud.insert("logs", {
                "ts": entry.get("ts"),
                "level": entry.get("level", "info"),
                "source": entry.get("source", "app"),
                "project_id": entry.get("project_id"),
                "task_id": entry.get("task_id"),
                "event": entry.get("event"),
                "message": entry.get("message"),
                "request_id": entry.get("request_id"),
            })
        except Exception as exc:
            _log.warning("log_svc.persist_failed", error=str(exc))

    def get_buffer_snapshot(self) -> list[dict]:
        """Return a copy of the in-memory buffer (for diagnostic bundles)."""
        return list(self._buffer)


log_svc = LogService()
