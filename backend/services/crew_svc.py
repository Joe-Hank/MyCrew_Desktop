from __future__ import annotations

import structlog

log = structlog.get_logger()


class CrewService:
    async def list_crews(self) -> list[dict]:
        return []

    async def get_crew(self, crew_id: str) -> dict | None:
        return None

    async def create_crew(self, data: dict) -> dict:
        raise NotImplementedError

    async def update_crew(self, crew_id: str, data: dict) -> dict:
        raise NotImplementedError

    async def delete_crew(self, crew_id: str) -> None:
        raise NotImplementedError


crew_svc = CrewService()
