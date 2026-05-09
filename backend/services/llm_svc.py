"""LLM service — CRUD for providers/models + quota/availability checks."""
from __future__ import annotations

import json

import structlog

from infra.llm.gateway import llm_gateway
from infra.repo import crud

log = structlog.get_logger()

JSON_FIELDS: list[str] = []


class LlmService:
    async def list_providers(self) -> list[dict]:
        providers = await crud.get_all("llm_providers")
        for p in providers:
            p["models"] = await crud.get_all("llm_models", "provider_id = ?", (p["id"],))
            for m in p["models"]:
                m["supports_thinking"] = bool(m.get("supports_thinking", 0))
        return providers

    async def get_provider(self, provider_id: str) -> dict | None:
        p = await crud.get_by_id("llm_providers", provider_id)
        if p:
            p["models"] = await crud.get_all("llm_models", "provider_id = ?", (p["id"],))
            for m in p["models"]:
                m["supports_thinking"] = bool(m.get("supports_thinking", 0))
        return p

    async def create_provider(self, data: dict) -> dict:
        row = await crud.insert("llm_providers", {
            "name": data["name"],
            "type": data["type"],
            "api_key_ref": data.get("api_key_ref"),
            "base_url": data.get("base_url"),
        }, id_prefix="llm_")
        row["models"] = []
        log.info("llm.provider_created", id=row["id"])
        return row

    async def update_provider(self, provider_id: str, data: dict) -> dict | None:
        fields = {k: v for k, v in data.items() if v is not None and k != "id"}
        return await crud.update_by_id("llm_providers", provider_id, fields)

    async def delete_provider(self, provider_id: str) -> None:
        from infra.repo.sqlite_repo import get_db
        db = await get_db()
        await db.execute("DELETE FROM llm_models WHERE provider_id = ?", (provider_id,))
        await crud.delete_by_id("llm_providers", provider_id)
        log.info("llm.provider_deleted", id=provider_id)

    async def create_model(self, data: dict) -> dict:
        row = await crud.insert("llm_models", {
            "provider_id": data["provider_id"],
            "model_name": data["model_name"],
            "label": data.get("label"),
            "max_tokens": data.get("max_tokens"),
            "supports_thinking": 1 if data.get("supports_thinking") else 0,
        }, id_prefix="mdl_")
        row["supports_thinking"] = bool(row.get("supports_thinking", 0))
        log.info("llm.model_created", id=row["id"])
        return row

    async def update_model(self, model_id: str, data: dict) -> dict | None:
        fields = {k: v for k, v in data.items() if v is not None and k != "id"}
        if "supports_thinking" in fields:
            fields["supports_thinking"] = 1 if fields["supports_thinking"] else 0
        result = await crud.update_by_id("llm_models", model_id, fields)
        if result:
            result["supports_thinking"] = bool(result.get("supports_thinking", 0))
        return result

    async def delete_model(self, model_id: str) -> None:
        await crud.delete_by_id("llm_models", model_id)
        log.info("llm.model_deleted", id=model_id)

    async def get_quota(self) -> list[dict]:
        """Check availability/quota for all configured providers.

        Returns a list of provider status objects with availability info.
        Rules from plan §11.2:
        - Returns percentage → integer percentage
        - Returns token count → unit M integer
        - Otherwise → green dot (available) / red dot (unavailable)
        """
        providers = await crud.get_all("llm_providers")
        results = []

        for provider in providers:
            status = {
                "provider_id": provider["id"],
                "name": provider["name"],
                "type": provider["type"],
                "available": False,
                "display": "red",  # red = unavailable, green = available
            }

            try:
                available = await llm_gateway.check_availability(provider["id"])
                status["available"] = available
                status["display"] = "green" if available else "red"
            except Exception as exc:
                log.warning("llm.quota_check_failed",
                            provider_id=provider["id"], error=str(exc))

            results.append(status)

        return results


llm_svc = LlmService()
