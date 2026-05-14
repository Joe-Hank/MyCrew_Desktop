"""Unity MCP: execute_custom_tool — 执行项目自定义工具."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ExecuteCustomToolArgs(BaseModel):
    """execute_custom_tool 参数."""
    tool_name: str = Field(..., description="自定义工具名称")
    parameters: dict | None = Field(default=None, description="工具参数字典")


def _run_execute_custom_tool(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "execute_custom_tool", args)


execute_custom_tool_tool = CrewStructuredTool.from_function(
    name="execute_custom_tool",
    description="执行项目中注册的自定义工具。通过 mcpforunity://custom-tools 资源发现可用工具。",
    func=_run_execute_custom_tool,
    args_schema=ExecuteCustomToolArgs,
)

__all__ = ["ExecuteCustomToolArgs", "execute_custom_tool_tool"]
