from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from infra.mcp.stdio_client import StdioMCPClient
from infra.mcp.http_client import HttpMCPClient

log = structlog.get_logger()

HEARTBEAT_INTERVAL = 30
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BACKOFF = [2, 4, 8, 16, 30]
# Per-server cap for initial auto-connect. If an MCP command hangs (e.g.
# `npx` waiting on a missing package or downloading), we must not block
# the whole app startup.
AUTO_CONNECT_TIMEOUT = 8


class MCPConnection:
    """Wraps a single MCP server connection with status tracking."""

    def __init__(self, server_id: str, config: dict) -> None:
        self.server_id = server_id
        self.config = config
        self.status: str = "disconnected"
        self.discovered_tools: list[dict] = []
        self.error_message: str | None = None
        self._reconnect_count = 0
        self._client: StdioMCPClient | HttpMCPClient | None = None

    def _build_client(self) -> StdioMCPClient | HttpMCPClient:
        transport = self.config.get("transport", "stdio")
        timeout = self.config.get("timeout", 30)
        if transport == "stdio":
            env_ref = self.config.get("env_ref", {})
            env = dict(env_ref) if env_ref else None
            return StdioMCPClient(
                server_id=self.server_id,
                command=self.config["command"],
                args=self.config.get("args", []),
                env=env,
                timeout=timeout,
            )
        else:
            url = self.config.get("url", "")
            return HttpMCPClient(
                server_id=self.server_id,
                url=url,
                timeout=timeout,
            )

    async def connect(self) -> None:
        if self.status == "connected":
            return
        self.status = "connecting"
        self.error_message = None
        try:
            self._client = self._build_client()
            await self._client.connect()
            self.discovered_tools = await self._client.list_tools()
            self.status = "connected"
            self._reconnect_count = 0
            log.info("mcp.pool.connected",
                     server_id=self.server_id,
                     tools=len(self.discovered_tools))
        except Exception as exc:
            self.status = "error"
            self.error_message = str(exc)
            self._client = None
            log.error("mcp.pool.connect_failed",
                      server_id=self.server_id, error=str(exc))
            raise

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None
        self.status = "disconnected"
        self.error_message = None

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if not self._client or not self._client.connected:
            raise RuntimeError(f"MCP server {self.server_id} not connected")
        return await self._client.call_tool(tool_name, arguments)

    async def health_check(self) -> bool:
        if not self._client or not self._client.connected:
            return False
        try:
            await self._client.list_tools()
            return True
        except Exception:
            return False

    async def try_reconnect(self) -> bool:
        if self._reconnect_count >= MAX_RECONNECT_ATTEMPTS:
            return False
        delay = RECONNECT_BACKOFF[min(self._reconnect_count, len(RECONNECT_BACKOFF) - 1)]
        self._reconnect_count += 1
        log.info("mcp.pool.reconnecting",
                 server_id=self.server_id, attempt=self._reconnect_count, delay=delay)
        await asyncio.sleep(delay)
        try:
            await self.disconnect()
            await self.connect()
            return True
        except Exception:
            return False

    def to_status_dict(self) -> dict:
        return {
            "server_id": self.server_id,
            "name": self.config.get("name", self.server_id),
            "transport": self.config.get("transport", "stdio"),
            "status": self.status,
            "tools_count": len(self.discovered_tools),
            "error": self.error_message,
        }


class MCPPool:
    """Manages all MCP server connections with heartbeat and auto-reconnect."""

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}
        self._heartbeat_task: asyncio.Task | None = None
        self._broadcast_fn = None
        self._sync_tools_fn = None

    def set_broadcast(self, fn) -> None:
        self._broadcast_fn = fn

    def set_tools_sync(self, fn) -> None:
        self._sync_tools_fn = fn

    async def start(self, servers: list[dict]) -> None:
        enabled = [s for s in servers if s.get("enabled", True)]
        auto_start = [s for s in enabled if s.get("auto_start", True)]

        # Cross-boot orphan sweep (2026-05-17): previous reload cycles
        # may have left npx/uvx zombies holding npm/uv cache locks.
        # Without this sweep, the new spawns below deadlock waiting
        # for those locks and the whole startup hangs forever (the
        # 8s wait_for has been observed not to fire reliably on
        # Windows ProactorEventLoop). See infra/mcp/subprocess_reaper.
        try:
            from infra.mcp.subprocess_reaper import sweep_orphan_mcp_subprocesses
            sweep_orphan_mcp_subprocesses(enabled)
        except Exception as exc:  # noqa: BLE001
            log.warning("mcp.pool.orphan_sweep_failed", error=str(exc))

        tasks = [self._safe_connect(s) for s in auto_start]
        if tasks:
            await asyncio.gather(*tasks)

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        log.info("mcp.pool.started",
                 total=len(servers), auto_started=len(auto_start))

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        tasks = [conn.disconnect() for conn in self._connections.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._connections.clear()

        # SDK's AsyncExitStack.aclose() routinely fails to clean up
        # subprocesses on Windows (the silent disconnect_error warnings
        # logged above). Reap any survivors so the next --reload cycle
        # doesn't inherit a growing pile of zombies.
        try:
            from infra.mcp.subprocess_reaper import reap_my_subprocesses
            reap_my_subprocesses(reason="pool.stop")
        except Exception as exc:  # noqa: BLE001
            log.warning("mcp.pool.reap_failed", error=str(exc))

        log.info("mcp.pool.stopped")

    async def connect_server(self, server_id: str, config: dict) -> dict:
        conn = MCPConnection(server_id, config)
        self._connections[server_id] = conn
        await conn.connect()
        await self._sync_discovered_tools(server_id, conn)
        await self._broadcast_status_change(server_id, conn)
        return conn.to_status_dict()

    async def disconnect_server(self, server_id: str) -> None:
        conn = self._connections.get(server_id)
        if conn:
            await conn.disconnect()
            await self._broadcast_status_change(server_id, conn)

    async def restart_server(self, server_id: str) -> dict:
        conn = self._connections.get(server_id)
        if not conn:
            raise KeyError(f"Server {server_id} not in pool")
        await conn.disconnect()
        await conn.connect()
        await self._sync_discovered_tools(server_id, conn)
        await self._broadcast_status_change(server_id, conn)
        return conn.to_status_dict()

    async def remove_server(self, server_id: str) -> None:
        conn = self._connections.pop(server_id, None)
        if conn:
            await conn.disconnect()

    async def call(self, server_id: str, tool_name: str, arguments: dict[str, Any]) -> str:
        conn = self._connections.get(server_id)
        if not conn:
            raise KeyError(f"Server {server_id} not in pool")
        return await conn.call_tool(tool_name, arguments)

    def get_connection_status(self, server_id: str) -> str:
        conn = self._connections.get(server_id)
        return conn.status if conn else "disconnected"

    def get_all_statuses(self) -> list[dict]:
        return [conn.to_status_dict() for conn in self._connections.values()]

    def get_status_summary(self) -> dict:
        statuses = self.get_all_statuses()
        online = sum(1 for s in statuses if s["status"] == "connected")
        return {
            "total": len(statuses),
            "online": online,
            "offline": len(statuses) - online,
            "servers": statuses,
        }

    async def refresh_all(self, servers: list[dict]) -> dict:
        for conn in list(self._connections.values()):
            await conn.disconnect()
        self._connections.clear()

        tasks = [self._safe_connect(s) for s in servers if s.get("enabled", True)]
        if tasks:
            await asyncio.gather(*tasks)
        return self.get_status_summary()

    async def _safe_connect(self, server_config: dict) -> None:
        server_id = server_config["id"]
        conn = MCPConnection(server_id, server_config)
        self._connections[server_id] = conn

        # HTTP MCP pre-flight (2026-05-17): probe the TCP port first.
        # The SDK's streamable / SSE client otherwise burns the full
        # `timeout` (30s default) trying to negotiate against a port
        # nobody is listening on — and on Windows ProactorEventLoop
        # this sometimes hangs longer than the wait_for() below
        # rescues. A cheap socket connect tells us in 2s whether the
        # backing daemon (Unity Editor + Bridge / similar) is alive.
        if server_config.get("transport") == "http":
            from infra.mcp.subprocess_reaper import http_url_reachable
            url = server_config.get("url") or ""
            if url and not http_url_reachable(url, timeout_s=2.0):
                conn.status = "error"
                conn.error_message = (
                    f"{url} refused TCP connect — backing server "
                    "(Unity Editor + MCP Bridge / similar) not running."
                )
                log.info("mcp.pool.http_preflight_skip",
                         server_id=server_id, url=url)
                await self._broadcast_status_change(server_id, conn)
                return

        try:
            # Hard timeout so a hanging stdio command can't block app startup.
            # On timeout the conn enters "error" — user can retry via UI later.
            await asyncio.wait_for(conn.connect(), timeout=AUTO_CONNECT_TIMEOUT)
            await self._sync_discovered_tools(server_id, conn)
        except asyncio.TimeoutError:
            log.warning("mcp.pool.auto_connect_timeout",
                        server_id=server_id, timeout=AUTO_CONNECT_TIMEOUT)
            conn.status = "error"
            conn.error_message = f"connect timeout after {AUTO_CONNECT_TIMEOUT}s"
            try:
                await conn.disconnect()
            except Exception:
                pass
        except Exception as exc:
            log.warning("mcp.pool.auto_connect_failed",
                        server_id=server_id, error=str(exc))
        await self._broadcast_status_change(server_id, conn)

    async def _heartbeat_loop(self) -> None:
        """Heartbeat loop with defensive outer try/except — a single failed
        check should never silently kill the whole task. We catch and continue.
        """
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                for server_id, conn in list(self._connections.items()):
                    try:
                        if conn.status != "connected":
                            if conn.status == "error":
                                reconnected = await conn.try_reconnect()
                                if reconnected:
                                    await self._sync_discovered_tools(server_id, conn)
                                    await self._broadcast_status_change(server_id, conn)
                            continue

                        alive = await conn.health_check()
                        if not alive:
                            log.warning("mcp.pool.heartbeat_failed", server_id=server_id)
                            conn.status = "error"
                            conn.error_message = "heartbeat failed"
                            await self._broadcast_status_change(server_id, conn)
                            reconnected = await conn.try_reconnect()
                            if reconnected:
                                await self._sync_discovered_tools(server_id, conn)
                                await self._broadcast_status_change(server_id, conn)
                    except Exception as exc:
                        log.error("mcp.pool.heartbeat_iter_failed",
                                  server_id=server_id, error=str(exc))
            except asyncio.CancelledError:
                raise  # graceful shutdown
            except Exception as exc:
                log.error("mcp.pool.heartbeat_loop_failed", error=str(exc))
                # Don't let one bad tick kill the loop forever — sleep & continue
                await asyncio.sleep(5)

    async def _sync_discovered_tools(self, server_id: str, conn: MCPConnection) -> None:
        if self._sync_tools_fn and conn.discovered_tools:
            try:
                await self._sync_tools_fn(server_id, conn.discovered_tools)
            except Exception as exc:
                log.warning("mcp.pool.tools_sync_failed",
                            server_id=server_id, error=str(exc))

    async def _broadcast_status_change(self, server_id: str, conn: MCPConnection) -> None:
        if self._broadcast_fn:
            try:
                await self._broadcast_fn("mcp.status_changed", conn.to_status_dict())
            except Exception:
                pass


mcp_pool = MCPPool()
