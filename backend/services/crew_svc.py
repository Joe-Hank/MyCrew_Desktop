from __future__ import annotations

import json
import structlog

from infra.repo import crud

log = structlog.get_logger()

JSON_FIELDS = ["agent_ids"]


class CrewService:
    async def list_crews(self) -> list[dict]:
        rows = await crud.get_all("crews")
        return [self._decode(r) for r in rows]

    async def get_crew(self, crew_id: str) -> dict | None:
        row = await crud.get_by_id("crews", crew_id)
        return self._decode(row) if row else None

    async def create_crew(self, data: dict) -> dict:
        store = self._encode(data)
        row = await crud.insert("crews", store, id_prefix="crw_")
        log.info("crew.created", crew_id=row["id"])
        return self._decode(row)

    async def update_crew(self, crew_id: str, data: dict) -> dict:
        existing = await crud.get_by_id("crews", crew_id)
        if not existing:
            raise KeyError(f"Crew {crew_id} not found")
        store = self._encode(data)
        row = await crud.update_by_id("crews", crew_id, store)
        log.info("crew.updated", crew_id=crew_id)
        return self._decode(row)

    async def delete_crew(self, crew_id: str) -> None:
        await crud.delete_by_id("crews", crew_id)
        log.info("crew.deleted", crew_id=crew_id)

    @staticmethod
    def _encode(data: dict) -> dict:
        out = dict(data)
        for f in JSON_FIELDS:
            if f in out and not isinstance(out[f], str):
                out[f] = json.dumps(out[f])
        for bf in ("is_auto_generated",):
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
        for bf in ("is_auto_generated",):
            if bf in out:
                out[bf] = bool(out[bf])
        return out


crew_svc = CrewService()
