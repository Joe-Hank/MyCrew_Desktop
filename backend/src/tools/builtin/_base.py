"""Base classes for CrewAI tools with permission guarding + audit + confirmation.

Two flavours:
  - GuardedMCPTool: wraps a remote MCP tool call (`mcp_pool.call`)
  - GuardedLocalTool: wraps an internal Python coroutine

Both enforce the permission matrix before the underlying operation, can
optionally require a user confirmation (high-risk tools), and emit a
`tool.invoked` audit event so the LogDrawer shows every tool call.

The asyncio bridge differs: MCP calls open a fresh loop in the calling
thread (safe because the MCP pool is stateless across loops). Local tools
must hop back to the main event loop because they touch aiosqlite /
WebSocket state that is bound to it.
"""
from __future__ import annotations

import asyncio
import time
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


# ── audit + confirmation helpers (thread-safe, bridge to main loop) ─

def _audit(tool_name: str, status: str, **extra: Any) -> None:
    """Fire-and-forget broadcast of a `tool.invoked` event for the LogDrawer.

    Called from arbitrary threads (CrewAI worker thread, MCP fresh loop
    thread); schedules `manager.broadcast` on the main loop where WS
    connection state lives. Failures are swallowed — audit must never
    break the underlying tool call.

    Noise control (2026-05-17): the 'started' status carries no debug
    info beyond what 'completed' already conveys (the latter has the
    same tool name + `duration_ms`). Roughly halved events-table size
    just by dropping it. Errors / denials still broadcast normally.
    """
    if status == "started":
        return
    from infra.runtime import get_main_loop
    try:
        from api.ws import manager
    except Exception:  # noqa: BLE001 — module may not be importable in tests
        return
    main_loop = get_main_loop()
    if main_loop is None or main_loop.is_closed():
        return
    payload = {"tool": tool_name, "status": status, **extra}
    try:
        asyncio.run_coroutine_threadsafe(
            manager.broadcast("tool.invoked", payload),
            main_loop,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("tool.audit_broadcast_failed",
                    tool=tool_name, error=str(exc))


def _confirm_high_risk(tool_name: str, title: str = "") -> bool:
    """Synchronously prompt the user for confirmation via the InteractionPort.

    Bridges to the main loop (where the WS broadcast + pending-request
    table live). Returns True if the user accepted, False on reject /
    timeout / any infra error. Blocks the calling thread for up to
    WsInteraction.DEFAULT_TIMEOUT (5 minutes).
    """
    from infra.runtime import run_on_main_loop
    from infra.interaction.ws_interaction import ws_interaction
    from ports.interaction_port import PromptCtx

    async def _ask() -> bool:
        return await ws_interaction.prompt_confirm(
            PromptCtx(title=title or f"确认执行 {tool_name}"),
        )

    try:
        return run_on_main_loop(_ask())
    except Exception as exc:  # noqa: BLE001 — deny on infra failure
        log.warning("tool.confirm_failed", tool=tool_name, error=str(exc))
        return False


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


# ── MCP-backed tools ─────────────────────────────────────────────

class GuardedMCPTool(BaseTool):
    """Base for tools that invoke a remote MCP server.

    Subclasses set `mcp_server_id`, `mcp_tool_name`, optionally
    `permission_kind` and `requires_confirmation`. CrewAI calls `_run()`
    synchronously; we bridge to asyncio via a fresh loop on the calling
    thread.
    """

    mcp_server_id: ClassVar[str] = ""
    mcp_tool_name: ClassVar[str] = ""
    permission_kind: ClassVar[str | None] = None
    # Set True for destructive / side-effectful tools so the user gets a
    # confirm dialog (via WsInteraction.prompt_confirm) BEFORE the call
    # fires. Default False — most tools are silent + gated by the matrix.
    requires_confirmation: ClassVar[bool] = False

    def _guarded_call(self, arguments: dict[str, Any]) -> str:
        started_at = time.monotonic()
        _audit(self.name, "started",
               kind="mcp", permission_kind=self.permission_kind,
               server=self.mcp_server_id, mcp_tool=self.mcp_tool_name)

        async def _run_async() -> str:
            await _enforce_permission(
                permission_kind=self.permission_kind,
                name=self.name,
                arguments=arguments,
            )
            return await mcp_pool.call(self.mcp_server_id, self.mcp_tool_name, arguments)

        try:
            # High-risk confirmation BEFORE running. Synchronous (blocking)
            # so the LLM sees the actual outcome rather than a placeholder.
            if self.requires_confirmation and not _confirm_high_risk(self.name):
                _audit(self.name, "denied", reason="user_declined")
                return (
                    f"[Cancelled] '{self.name}' requires confirmation and the "
                    "user declined."
                )
            result = _run_in_fresh_loop(_run_async())
            _audit(self.name, "completed",
                   duration_ms=int((time.monotonic() - started_at) * 1000))
            return result
        except PermissionDenied as exc:
            log.warning("tool.permission_denied", tool=self.name, kind=exc.kind)
            _audit(self.name, "denied", reason="permission_disabled", kind=exc.kind)
            return (
                f"[PermissionDenied] Tool '{self.name}' blocked: "
                f"permission '{exc.kind}' is disabled in system settings."
            )
        except Exception as exc:
            log.error("tool.execution_failed", tool=self.name, error=str(exc))
            _audit(self.name, "failed", error=str(exc)[:200])
            raise


# ── Local-Python tools ────────────────────────────────────────────

class GuardedLocalTool(BaseTool):
    """Base for tools that call internal Python services directly.

    These tools typically need to touch aiosqlite / WebSocket state
    bound to the main event loop, so they hop back via
    `infra.runtime.run_on_main_loop`. CrewAI invokes `_run()` from a
    worker thread (we call `asyncio.to_thread(crew.kickoff)` upstream),
    so we cannot use the calling thread's loop.
    """

    permission_kind: ClassVar[str | None] = None
    requires_confirmation: ClassVar[bool] = False

    def _guarded_local(
        self, coro_factory: Callable[[], Awaitable[Any]]
    ) -> Any:
        """Run a permission check, optional confirmation, then the
        coroutine returned by `coro_factory()`, all on the main loop."""
        from infra.runtime import run_on_main_loop

        started_at = time.monotonic()
        _audit(self.name, "started",
               kind="local", permission_kind=self.permission_kind)

        async def _wrap() -> Any:
            await _enforce_permission(
                permission_kind=self.permission_kind,
                name=self.name,
                arguments={},  # local tools self-validate; no args dict to inspect
            )
            return await coro_factory()

        try:
            if self.requires_confirmation and not _confirm_high_risk(self.name):
                _audit(self.name, "denied", reason="user_declined")
                return (
                    f"[Cancelled] '{self.name}' requires confirmation and the "
                    "user declined."
                )
            result = run_on_main_loop(_wrap())
            _audit(self.name, "completed",
                   duration_ms=int((time.monotonic() - started_at) * 1000))
            return result
        except PermissionDenied as exc:
            log.warning("tool.permission_denied", tool=self.name, kind=exc.kind)
            _audit(self.name, "denied", reason="permission_disabled", kind=exc.kind)
            return (
                f"[PermissionDenied] Tool '{self.name}' blocked: "
                f"permission '{exc.kind}' is disabled in system settings."
            )
        except Exception as exc:
            log.error("tool.local_execution_failed", tool=self.name, error=str(exc))
            _audit(self.name, "failed", error=str(exc)[:200])
            raise
