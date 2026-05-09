from __future__ import annotations

import structlog

log = structlog.get_logger()


class AgentService:
    async def list_agents(self) -> list[dict]:
        return []

    async def get_agent(self, agent_id: str) -> dict | None:
        return None

    async def create_agent(self, data: dict) -> dict:
        raise NotImplementedError

    async def update_agent(self, agent_id: str, data: dict) -> dict:
        raise NotImplementedError

    async def delete_agent(self, agent_id: str) -> None:
        raise NotImplementedError


agent_svc = AgentService()
