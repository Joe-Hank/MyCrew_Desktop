"""Base class for MCP-wrapping CrewAI BaseTools with permission guarding.

Each subclass declares `mcp_server_id`, `mcp_tool_name`, and optionally
`permission_kind` to enable permission-matrix enforcement before the
underlying MCP call.
"""
from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import structlog
from crewai.tools import BaseTool

from infra.mcp.pool import mcp_pool
from services.permission_guard import (
    PermissionDenied,
    check_tool_permissions,
    require_permission,
)

log = structlog.get_logger()


class GuardedMCPTool(BaseTool):
    """Base for MCP-backed tools — enforces permission matrix before invoking.

    Subclasses can either:
    - set `permission_kind` class attribute (e.g. "file_read") for static enforcement
    - rely on tool-name heuristics via `check_tool_permissions`
    """

    # Subclasses override these
    mcp_server_id: ClassVar[str] = ""
    mcp_tool_name: ClassVar[str] = ""
    # Optional explicit permission kind; if None, name-based heuristics apply
    permission_kind: ClassVar[str | None] = None

    def _guarded_call(self, arguments: dict[str, Any]) -> str:
        """Run permission check + MCP call in one sync entrypoint.

        CrewAI invokes _run() synchronously, so we bridge to asyncio here.
        """
        async def _run_async() -> str:
            if self.permission_kind:
                await require_permission(self.permission_kind)
            else:
                await check_tool_permissions(self.name, arguments)
            return await mcp_pool.call(self.mcp_server_id, self.mcp_tool_name, arguments)

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            return loop.run_until_complete(_run_async())
        except PermissionDenied as exc:
            log.warning("tool.permission_denied", tool=self.name, kind=exc.kind)
            return f"[PermissionDenied] Tool '{self.name}' blocked: permission '{exc.kind}' is disabled in system settings."
        except Exception as exc:
            log.error("tool.execution_failed", tool=self.name, error=str(exc))
            raise
