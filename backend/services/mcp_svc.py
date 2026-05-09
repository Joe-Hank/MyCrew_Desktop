from __future__ import annotations

import structlog

log = structlog.get_logger()


class McpService:
    async def list_servers(self) -> list[dict]:
        return []

    async def add_server(self, data: dict) -> dict:
        raise NotImplementedError

    async def restart_server(self, server_id: str) -> dict:
        raise NotImplementedError

    async def refresh_all(self) -> dict:
        raise NotImplementedError

    async def shutdown_all(self) -> None:
        pass

    async def get_status_summary(self) -> dict:
        return {"total": 0, "online": 0, "offline": 0}


mcp_svc = McpService()
