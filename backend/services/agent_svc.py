from __future__ import annotations

import json
import structlog

from infra.repo import crud

log = structlog.get_logger()

JSON_FIELDS = ["tool_ids"]


class AgentService:
    async def list_agents(self) -> list[dict]:
        rows = await crud.get_all("agents")
        return [self._decode(r) for r in rows]

    async def get_agent(self, agent_id: str) -> dict | None:
        row = await crud.get_by_id("agents", agent_id)
        return self._decode(row) if row else None

    async def create_agent(self, data: dict) -> dict:
        store = self._encode(data)
        row = await crud.insert("agents", store, id_prefix="agt_")
        log.info("agent.created", agent_id=row["id"])
        return self._decode(row)

    async def update_agent(self, agent_id: str, data: dict) -> dict:
        existing = await crud.get_by_id("agents", agent_id)
        if not existing:
            raise KeyError(f"Agent {agent_id} not found")
        store = self._encode(data)
        row = await crud.update_by_id("agents", agent_id, store)
        log.info("agent.updated", agent_id=agent_id)
        return self._decode(row)

    async def delete_agent(self, agent_id: str) -> None:
        await crud.delete_by_id("agents", agent_id)
        log.info("agent.deleted", agent_id=agent_id)

    @staticmethod
    def _encode(data: dict) -> dict:
        out = dict(data)
        for f in JSON_FIELDS:
            if f in out and not isinstance(out[f], str):
                out[f] = json.dumps(out[f])
        for bf in ("reasoning", "memory_enabled", "thinking_mode"):
            if bf in out and isinstance(out[bf], bool):
                out[bf] = 1 if out[bf] else 0
        return out

    @staticmethod
    def _decode(row: dict) -> dict:
        out = dict(row)
        for f in JSON_FIELDS:
            if f in out and isinstance(out[f], str):
                try:
                    out[f] = json.loads(out[f])
                except (json.JSONDecodeError, TypeError):
                    out[f] = []
        for bf in ("reasoning", "memory_enabled", "thinking_mode", "is_auto_generated"):
            if bf in out:
                out[bf] = bool(out[bf])
        return out


agent_svc = AgentService()
