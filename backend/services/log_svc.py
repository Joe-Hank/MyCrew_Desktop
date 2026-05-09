from __future__ import annotations

import structlog

log = structlog.get_logger()


class LogService:
    async def query(
        self,
        source: str | None = None,
        level: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return []

    async def append(self, entry: dict) -> None:
        raise NotImplementedError


log_svc = LogService()
