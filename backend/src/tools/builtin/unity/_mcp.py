"""
Unity MCP 连接池基础设施。

本模块提供与 Unity MCP Bridge 通信的统一入口，
支持 MCP Streamable HTTP + SSE 传输协议。

使用方式：
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    result = pool.call("unity", "manage_gameobject", {"action": "find", ...})

设计原则：
    - 单例连接池：整个进程生命周期内复用 MCP 连接
    - Lazy 初始化：首次调用时才连接，避免启动阻塞
    - 容错：连接失败时返回可读的错误信息供 LLM 理解
    - 支持 Streamable HTTP + SSE 传输（MCP 2024-11-05 协议）
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 连接池配置
# ---------------------------------------------------------------------------
_UNITY_MCP_URL = os.environ.get("UNITY_MCP_URL", "http://127.0.0.1:8090/mcp")


class _UnityMcpPool:
    """
    Unity MCP 连接池（懒加载单例）。

    封装与 Unity MCP Bridge 的通信：
      - call(server_id, tool_name, args) → 调用指定 MCP 工具并返回格式化结果
      - 自动处理 MCP 协议握手（initialize → initialized → tools/call）
      - 支持 Streamable HTTP + SSE 传输
    """

    _instance: _UnityMcpPool | None = None

    def __init__(self) -> None:
        self._initialized = False
        self._session_id: str | None = None
        self._request_id = 0
        self._mcp_pool: Any = None

    @classmethod
    def get_instance(cls) -> _UnityMcpPool:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _ensure_initialized(self) -> bool:
        """确保 MCP 会话已初始化."""
        if self._initialized and self._session_id:
            return True

        # 尝试从 DI 容器获取（生产路径）
        try:
            from src.bootstrap.container import get_container  # type: ignore[import-not-found]
            container = get_container()
            self._mcp_pool = container.mcp_pool  # type: ignore[attr-defined]
            if self._mcp_pool is not None:
                self._initialized = True
                logger.info("Unity MCP pool initialized via DI container")
                return True
        except Exception:
            pass

        # 直接通过 Streamable HTTP 初始化
        try:
            result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "MyCrew-Unity", "version": "1.0.0"},
            })
            if result and "protocolVersion" in str(result):
                # Send initialized notification
                self._send_notification("notifications/initialized", {})
                self._initialized = True
                logger.info("Unity MCP session initialized: %s", self._session_id)
                return True
        except Exception as e:
            logger.error("Failed to initialize Unity MCP session: %s", e)

        return False

    def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        """发送 JSON-RPC 请求并解析 SSE 响应."""
        import urllib.request
        import urllib.error

        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._next_id(),
        }).encode("utf-8")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        req = urllib.request.Request(
            _UNITY_MCP_URL, data=payload, headers=headers, method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                # 提取 session ID
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self._session_id = sid

                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read().decode("utf-8")

                if "text/event-stream" in content_type:
                    return self._parse_sse(raw)
                else:
                    return json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") if e.fp else ""
            return {"error": f"HTTP {e.code}: {body[:500]}"}
        except urllib.error.URLError as e:
            return {"error": f"连接失败: {e.reason}"}

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """发送 JSON-RPC 通知（无 id，不期望响应）."""
        import urllib.request
        import urllib.error

        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }).encode("utf-8")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        req = urllib.request.Request(
            _UNITY_MCP_URL, data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()  # drain
        except Exception:
            pass  # notifications don't require response

    def _parse_sse(self, raw: str) -> Any:
        """解析 SSE 响应，提取最后一个 data 事件."""
        result = None
        for line in raw.split("\n"):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    # 提取 JSON-RPC result
                    if "result" in data:
                        result = data["result"]
                    elif "error" in data:
                        result = data["error"]
                    else:
                        result = data
                except json.JSONDecodeError:
                    pass
        return result

    def call(self, server_id: str, tool_name: str, args: dict[str, Any]) -> str:
        """
        调用指定 Unity MCP 工具.

        Returns:
            MCP 工具返回的字符串结果；连接失败时返回错误描述
        """
        if not self._ensure_initialized():
            return (
                "ERROR: Unity MCP Bridge 未连接。"
                "请确认 Unity Editor 已启动并开启了 MCP Bridge。\n"
                f"  当前端点: {_UNITY_MCP_URL}\n"
                "  可通过环境变量 UNITY_MCP_URL 修改端口。"
            )

        # 如果有 DI 容器的 pool，使用它
        if self._mcp_pool is not None:
            try:
                if hasattr(self._mcp_pool, "call_tool"):
                    result = self._mcp_pool.call_tool(server_id, tool_name, args)
                else:
                    result = self._mcp_pool.call(server_id, tool_name, args)
                return _normalize_result(result)
            except Exception as e:
                logger.exception("Unity MCP DI call failed")
                return f"ERROR: {e}"

        # 直接 HTTP 调用
        result = self._send_request("tools/call", {"name": tool_name, "arguments": args})

        if result is None:
            return "ERROR: MCP 工具无返回值"
        if isinstance(result, dict) and "error" in result:
            return f"ERROR: {result['error']}"

        return _normalize_result(result)


def _normalize_result(result: Any) -> str:
    """将 MCP 返回结果归一化为字符串."""
    if result is None:
        return "MCP 工具执行完成，无返回值。"
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # MCP tool result has content array
        if "content" in result:
            texts = []
            for item in result["content"]:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item["text"])
            if texts:
                return "\n".join(texts)
        return json.dumps(result, ensure_ascii=False, indent=2)
    if isinstance(result, list):
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def get_unity_mcp_pool() -> _UnityMcpPool:
    """获取 Unity MCP 连接池单例."""
    return _UnityMcpPool.get_instance()


def _reset_pool() -> None:
    """重置单例（仅用于测试）."""
    _UnityMcpPool._instance = None
