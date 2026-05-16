from __future__ import annotations

import json
from typing import Any

import structlog

from infra.repo import crud
from infra.mcp.pool import mcp_pool

log = structlog.get_logger()

JSON_FIELDS = ["args", "env_ref", "discovered_tools", "template_values"]


class McpService:
    def __init__(self) -> None:
        self._pool = mcp_pool

    # ── CRUD ──────────────────────────────────────────────

    async def list_servers(self) -> list[dict]:
        rows = await crud.get_all("mcp_servers")
        result = [self._deserialize(r) for r in rows]
        for server in result:
            server["runtime_status"] = self._pool.get_connection_status(server["id"])
        return result

    async def get_server(self, server_id: str) -> dict | None:
        row = await crud.get_by_id("mcp_servers", server_id)
        if not row:
            return None
        result = self._deserialize(row)
        result["runtime_status"] = self._pool.get_connection_status(server_id)
        return result

    async def create_server(self, data: dict) -> dict:
        merged = self._apply_template(data)
        row = await crud.insert("mcp_servers", self._serialize({
            "name": merged["name"],
            "transport": merged.get("transport", "stdio"),
            "command": merged.get("command"),
            "args": merged.get("args", []),
            "url": merged.get("url"),
            "env_ref": merged.get("env_ref", {}),
            "enabled": 1 if merged.get("enabled", True) else 0,
            "auto_start": 1 if merged.get("auto_start", True) else 0,
            "timeout": merged.get("timeout", 30),
            "discovered_tools": [],
            "template_id": merged.get("template_id"),
            "template_values": merged.get("template_values") or {},
        }), id_prefix="mcp_")
        log.info("mcp.server_created", id=row["id"], template=merged.get("template_id"))
        return self._deserialize(row)

    async def update_server(self, server_id: str, data: dict) -> dict | None:
        # If the patch carries template_id / template_values, re-derive
        # command/args/url/env_ref from the template before persisting.
        # Lets the frontend send just {template_id, template_values}
        # and have the backend figure out everything else.
        if "template_id" in data and data["template_id"]:
            merged = self._apply_template(data)
            for k in ("command", "args", "url", "env_ref",
                      "transport", "template_values"):
                if k in merged:
                    data[k] = merged[k]
        fields = {k: v for k, v in data.items() if v is not None and k != "id"}
        if "enabled" in fields:
            fields["enabled"] = 1 if fields["enabled"] else 0
        if "auto_start" in fields:
            fields["auto_start"] = 1 if fields["auto_start"] else 0
        serialized = self._serialize(fields)
        result = await crud.update_by_id("mcp_servers", server_id, serialized)
        return self._deserialize(result) if result else None

    def _apply_template(self, data: dict) -> dict:
        """Resolve template_id + template_values → concrete fields.

        - When `template_id` is set (and not 'custom'), assemble the
          command/args/url/env_ref from the template, raising
          TemplateValidationError on missing / placeholder fields.
        - When 'custom' or absent, pass the data through unchanged.
        """
        from services.mcp_templates import (
            assemble, get_template, TemplateValidationError,
        )

        out = dict(data)
        template_id = out.get("template_id")
        if not template_id or template_id == "custom":
            return out
        template = get_template(template_id)
        if not template:
            raise ValueError(f"Unknown template_id: {template_id!r}")
        values = out.get("template_values") or {}
        try:
            assembled = assemble(template, values)
        except TemplateValidationError:
            raise  # let the route layer surface field errors to the user
        out.update(assembled)
        out["template_values"] = values
        return out

    async def delete_server(self, server_id: str) -> None:
        await self._pool.remove_server(server_id)
        await crud.delete_by_id("mcp_servers", server_id)
        log.info("mcp.server_deleted", id=server_id)

    # ── Pool operations ───────────────────────────────────

    async def connect_server(self, server_id: str) -> dict:
        server = await self.get_server(server_id)
        if not server:
            raise KeyError(f"Server {server_id} not found")
        return await self._pool.connect_server(server_id, server)

    async def disconnect_server(self, server_id: str) -> None:
        await self._pool.disconnect_server(server_id)

    async def restart_server(self, server_id: str) -> dict:
        server = await self.get_server(server_id)
        if not server:
            raise KeyError(f"Server {server_id} not found")
        if self._pool.get_connection_status(server_id) == "disconnected":
            return await self._pool.connect_server(server_id, server)
        return await self._pool.restart_server(server_id)

    async def call_tool(self, server_id: str, tool_name: str,
                        arguments: dict[str, Any]) -> str:
        return await self._pool.call(server_id, tool_name, arguments)

    async def refresh_all(self) -> dict:
        servers = await self.list_servers()
        return await self._pool.refresh_all(servers)

    async def start_pool(self) -> None:
        servers = await self.list_servers()
        self._pool.set_tools_sync(self._sync_tools_to_db)
        await self._pool.start(servers)

    async def shutdown_all(self) -> None:
        await self._pool.stop()

    async def backfill_template_ids(self) -> int:
        """One-shot at startup: for rows that don't yet have template_id,
        detect it by command+args fingerprint and stamp the row.

        Idempotent — rows already tagged are skipped. Returns the count
        of rows newly tagged (informational).
        """
        from services.mcp_templates import detect_template
        rows = await crud.get_all("mcp_servers")
        tagged = 0
        for r in rows:
            if r.get("template_id"):
                continue
            detected = detect_template(r)
            if not detected:
                detected = "custom"
            await crud.update_by_id("mcp_servers", r["id"], {
                "template_id": detected,
            })
            tagged += 1
        if tagged:
            log.info("mcp.template_id_backfilled", rows=tagged)
        return tagged

    async def get_status_summary(self) -> dict:
        total = await crud.count("mcp_servers")
        enabled = await crud.count("mcp_servers", "enabled = 1")
        pool_status = self._pool.get_status_summary()
        return {
            "total": total,
            "enabled": enabled,
            "online": pool_status["online"],
            "offline": pool_status["offline"],
            "servers": pool_status["servers"],
        }

    # ── Internal helpers ──────────────────────────────────

    async def _sync_tools_to_db(self, server_id: str, tools: list[dict]) -> None:
        await crud.update_by_id("mcp_servers", server_id, {
            "discovered_tools": json.dumps(tools),
        })
        log.info("mcp.tools_synced", server_id=server_id, count=len(tools))

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
