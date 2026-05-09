from __future__ import annotations

import structlog

log = structlog.get_logger()


class LlmService:
    async def list_providers(self) -> list[dict]:
        return []

    async def get_provider(self, provider_id: str) -> dict | None:
        return None

    async def upsert_provider(self, data: dict) -> dict:
        raise NotImplementedError

    async def delete_provider(self, provider_id: str) -> None:
        raise NotImplementedError

    async def get_quota(self) -> list[dict]:
        return []


llm_svc = LlmService()
