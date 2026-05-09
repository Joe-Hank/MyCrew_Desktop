from __future__ import annotations

import structlog

log = structlog.get_logger()


class ToolService:
    async def list_tools(self) -> list[dict]:
        return []

    async def get_tool(self, tool_id: str) -> dict | None:
        return None

    async def create_tool(self, data: dict) -> dict:
        raise NotImplementedError

    async def update_tool(self, tool_id: str, data: dict) -> dict:
        raise NotImplementedError

    async def delete_tool(self, tool_id: str) -> None:
        raise NotImplementedError

    async def scan_tools_dir(self) -> list[dict]:
        return []


tool_svc = ToolService()
