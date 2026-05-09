from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import structlog
from mcp import ClientSession

log = structlog.get_logger()


def _get_sse_client():
    try:
        from mcp.client.sse import sse_client
        return sse_client
    except ImportError:
        return None


def _get_streamable_http_client():
    try:
        from mcp.client.streamable_http import streamablehttp_client
        return streamablehttp_client
    except ImportError:
        return None


class HttpMCPClient:
    """Manages a single HTTP-transport MCP server connection (SSE or Streamable HTTP)."""

    def __init__(self, server_id: str, url: str, timeout: int = 30) -> None:
        self.server_id = server_id
        self._url = url
        self._timeout = timeout
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

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
            transport = await self._open_transport(stack)
            read_stream, write_stream = transport[0], transport[1]
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await asyncio.wait_for(session.initialize(), timeout=self._timeout)

            self._exit_stack = stack
            self._session = session
            log.info("mcp.http.connected", server_id=self.server_id, url=self._url)
            return session
        except Exception:
            await stack.aclose()
            raise

    async def _open_transport(self, stack: AsyncExitStack):
        streamable = _get_streamable_http_client()
        if streamable is not None:
            try:
                return await asyncio.wait_for(
                    stack.enter_async_context(streamable(self._url)),
                    timeout=self._timeout,
                )
            except Exception:
                log.debug("mcp.http.streamable_failed, falling back to SSE",
                          server_id=self.server_id)

        sse = _get_sse_client()
        if sse is not None:
            return await asyncio.wait_for(
                stack.enter_async_context(sse(self._url)),
                timeout=self._timeout,
            )

        raise RuntimeError("No HTTP MCP transport available (need mcp[sse] or mcp[streamable-http])")

    async def disconnect(self) -> None:
        if self._exit_stack is not None:
            try:
                await asyncio.wait_for(self._exit_stack.aclose(), timeout=5)
            except Exception:
                log.warning("mcp.http.disconnect_error", server_id=self.server_id)
            self._exit_stack = None
            self._session = None
            log.info("mcp.http.disconnected", server_id=self.server_id)

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
