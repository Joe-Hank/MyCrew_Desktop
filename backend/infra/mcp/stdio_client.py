from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import structlog
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

log = structlog.get_logger()


class StdioMCPClient:
    """Manages a single stdio-transport MCP server connection."""

    def __init__(self, server_id: str, command: str, args: list[str],
                 env: dict[str, str] | None = None, timeout: int = 30) -> None:
        self.server_id = server_id
        self._params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )
        self._timeout = timeout
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._process_pid: int | None = None

    @property
    def session(self) -> ClientSession | None:
        return self._session

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> ClientSession:
        if self._session is not None:
            return self._session

        stack = AsyncExitStack()
        try:
            transport = await asyncio.wait_for(
                stack.enter_async_context(stdio_client(self._params)),
                timeout=self._timeout,
            )
            read_stream, write_stream = transport
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await asyncio.wait_for(session.initialize(), timeout=self._timeout)

            self._exit_stack = stack
            self._session = session
            log.info("mcp.stdio.connected", server_id=self.server_id)
            return session
        except Exception:
            await stack.aclose()
            raise

    async def disconnect(self) -> None:
        if self._exit_stack is not None:
            try:
                await asyncio.wait_for(self._exit_stack.aclose(), timeout=5)
            except Exception:
                log.warning("mcp.stdio.disconnect_error", server_id=self.server_id)
            self._exit_stack = None
            self._session = None
            log.info("mcp.stdio.disconnected", server_id=self.server_id)

    async def list_tools(self) -> list[dict]:
        if not self._session:
            return []
        result = await self._session.list_tools()
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema if hasattr(t, "inputSchema") else {},
            }
            for t in result.tools
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if not self._session:
            raise RuntimeError(f"MCP server {self.server_id} not connected")
        result = await asyncio.wait_for(
            self._session.call_tool(tool_name, arguments=arguments),
            timeout=self._timeout,
        )
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)
