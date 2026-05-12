"""Base classes for CrewAI tools with permission guarding.

Two flavours:
  - GuardedMCPTool: wraps a remote MCP tool call (`mcp_pool.call`)
  - GuardedLocalTool: wraps an internal Python coroutine

Both enforce the permission matrix before the underlying operation. The
asyncio bridge differs: MCP calls open a fresh loop in the calling thread
(safe because the MCP pool is stateless across loops). Local tools must
hop back to the main event loop because they touch aiosqlite / WebSocket
state that is bound to it.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, ClassVar

import structlog
from crewai.tools import BaseTool

from infra.mcp.pool import mcp_pool
from services.permission_guard import (
    PermissionDenied,
    check_tool_permissions,
    require_permission,
)

log = structlog.get_logger()


# ── shared helpers ────────────────────────────────────────────────

def _run_in_fresh_loop(coro: Awaitable[Any]) -> Any:
    """Run a coroutine in a brand-new event loop on the current thread.

    Used by MCP tools — the call doesn't touch any state bound to the
    main loop, so a private loop is fine.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're on a thread with a running loop. Don't reenter; open a private one.
            raise RuntimeError("loop already running")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _enforce_permission(
    *, permission_kind: str | None, name: str, arguments: dict[str, Any]
) -> None:
    """Shared permission check used by both tool flavours."""
    if permission_kind:
        await require_permission(permission_kind)
    else:
        await check_tool_permissions(name, arguments)


# ── MCP-backed tools (unchanged public API) ────────────────────────

class GuardedMCPTool(BaseTool):
    """Base for tools that invoke a remote MCP server.

    Subclasses set `mcp_server_id`, `mcp_tool_name`, optionally
    `permission_kind`. CrewAI calls `_run()` synchronously; we bridge to
    asyncio via a fresh loop on the calling thread.
    """

    mcp_server_id: ClassVar[str] = ""
    mcp_tool_name: ClassVar[str] = ""
    permission_kind: ClassVar[str | None] = None

    def _guarded_call(self, arguments: dict[str, Any]) -> str:
        async def _run_async() -> str:
            await _enforce_permission(
                permission_kind=self.permission_kind,
                name=self.name,
                arguments=arguments,
            )
            return await mcp_pool.call(self.mcp_server_id, self.mcp_tool_name, arguments)

        try:
            return _run_in_fresh_loop(_run_async())
        except PermissionDenied as exc:
            log.warning("tool.permission_denied", tool=self.name, kind=exc.kind)
            return (
                f"[PermissionDenied] Tool '{self.name}' blocked: "
                f"permission '{exc.kind}' is disabled in system settings."
            )
        except Exception as exc:
            log.error("tool.execution_failed", tool=self.name, error=str(exc))
            raise


# ── Local-Python tools (new) ──────────────────────────────────────

class GuardedLocalTool(BaseTool):
    """Base for tools that call internal Python services directly.

    These tools typically need to touch aiosqlite / WebSocket state
    bound to the main event loop, so they hop back via
    `infra.runtime.run_on_main_loop`. CrewAI invokes `_run()` from a
    worker thread (we call `asyncio.to_thread(crew.kickoff)` upstream),
    so we cannot use the calling thread's loop.
    """

    permission_kind: ClassVar[str | None] = None

    def _guarded_local(
        self, coro_factory: Callable[[], Awaitable[Any]]
    ) -> Any:
        """Run a permission check, then the coroutine returned by
        `coro_factory()`, both on the main event loop."""
        from infra.runtime import run_on_main_loop

        async def _wrap() -> Any:
            await _enforce_permission(
                permission_kind=self.permission_kind,
                name=self.name,
                arguments={},  # local tools self-validate; no args dict to inspect
            )
            return await coro_factory()

        try:
            return run_on_main_loop(_wrap())
        except PermissionDenied as exc:
            log.warning("tool.permission_denied", tool=self.name, kind=exc.kind)
            return (
                f"[PermissionDenied] Tool '{self.name}' blocked: "
                f"permission '{exc.kind}' is disabled in system settings."
            )
        except Exception as exc:
            log.error("tool.local_execution_failed", tool=self.name, error=str(exc))
            raise
