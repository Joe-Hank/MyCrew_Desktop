from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

import structlog

_log = structlog.get_logger()

MAX_BUFFER = 2000


class LogService:
    def __init__(self) -> None:
        self._buffer: deque[dict] = deque(maxlen=MAX_BUFFER)

    async def query(
        self,
        source: str | None = None,
        level: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        results = list(self._buffer)
        if source:
            results = [r for r in results if r.get("source") == source]
        if level:
            results = [r for r in results if r.get("level") == level]
        if since:
            results = [r for r in results if r.get("ts", "") >= since]
        return results[-limit:]

    async def append(self, entry: dict) -> None:
        if "ts" not in entry:
            entry["ts"] = datetime.now(timezone.utc).isoformat()
        self._buffer.append(entry)


log_svc = LogService()
