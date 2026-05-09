from __future__ import annotations

import json

import structlog

from infra.repo import crud

log = structlog.get_logger()

JSON_FIELDS = ["args", "env_ref", "discovered_tools"]


class McpService:
    async def list_servers(self) -> list[dict]:
        rows = await crud.get_all("mcp_servers")
        return [self._deserialize(r) for r in rows]

    async def get_server(self, server_id: str) -> dict | None:
        row = await crud.get_by_id("mcp_servers", server_id)
        return self._deserialize(row) if row else None

    async def create_server(self, data: dict) -> dict:
        row = await crud.insert("mcp_servers", self._serialize({
            "name": data["name"],
            "transport": data.get("transport", "stdio"),
            "command": data.get("command"),
            "args": data.get("args", []),
            "url": data.get("url"),
            "env_ref": data.get("env_ref", {}),
            "enabled": 1 if data.get("enabled", True) else 0,
            "auto_start": 1 if data.get("auto_start", True) else 0,
            "timeout": data.get("timeout", 30),
            "discovered_tools": [],
        }), id_prefix="mcp_")
        log.info("mcp.server_created", id=row["id"])
        return self._deserialize(row)

    async def update_server(self, server_id: str, data: dict) -> dict | None:
        fields = {k: v for k, v in data.items() if v is not None and k != "id"}
        if "enabled" in fields:
            fields["enabled"] = 1 if fields["enabled"] else 0
        if "auto_start" in fields:
            fields["auto_start"] = 1 if fields["auto_start"] else 0
        serialized = self._serialize(fields)
        result = await crud.update_by_id("mcp_servers", server_id, serialized)
        return self._deserialize(result) if result else None

    async def delete_server(self, server_id: str) -> None:
        await crud.delete_by_id("mcp_servers", server_id)
        log.info("mcp.server_deleted", id=server_id)

    async def refresh_all(self) -> dict:
        return {"refreshed": 0}

    async def shutdown_all(self) -> None:
        pass

    async def get_status_summary(self) -> dict:
        total = await crud.count("mcp_servers")
        enabled = await crud.count("mcp_servers", "enabled = 1")
        return {"total": total, "online": 0, "offline": enabled}

    def _serialize(self, data: dict) -> dict:
        out = dict(data)
        for f in JSON_FIELDS:
            if f in out and not isinstance(out[f], str):
                out[f] = json.dumps(out[f])
        return out

    def _deserialize(self, data: dict) -> dict:
        out = dict(data)
        for f in JSON_FIELDS:
            if f in out and isinstance(out[f], str):
                try:
                    out[f] = json.loads(out[f])
                except (json.JSONDecodeError, TypeError):
                    pass
        out["enabled"] = bool(out.get("enabled", 1))
        out["auto_start"] = bool(out.get("auto_start", 1))
        return out


mcp_svc = McpService()
