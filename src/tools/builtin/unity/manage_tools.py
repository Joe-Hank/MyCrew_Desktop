"""
Unity MCP: manage_tools — 管理 MCP 工具开关状态。

对 Unity MCP Bridge 提供的所有工具进行启用/禁用/列出操作。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


# =============================================================================
# args_schema
# =============================================================================

class ManageToolsArgs(BaseModel):
    """manage_tools 参数."""
    action: str = Field(
        ...,
        description=(
            "Action to perform:\n"
            "  list — 列出所有 MCP 工具及其启用状态 (无必需额外参数)\n"
            "  enable — 启用指定工具 (必需: tool_name; 可选: reason)\n"
            "  disable — 禁用指定工具 (必需: tool_name; 可选: reason)"
        ),
    )
    tool_name: str | None = Field(
        default=None,
        description="要启用/禁用的工具名称（enable/disable 时必需）",
    )
    reason: str | None = Field(
        default=None,
        description="启用/禁用的原因说明",
    )


# =============================================================================
# 执行函数
# =============================================================================

def _run_manage_tools(
    action: str,
    tool_name: str | None = None,
    reason: str | None = None,
) -> str:
    """执行 Unity MCP manage_tools."""
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool

    pool = get_unity_mcp_pool()
    args: dict[str, Any] = {"action": action}
    if tool_name is not None:
        args["tool_name"] = tool_name
    if reason is not None:
        args["reason"] = reason

    return pool.call("unity", "manage_tools", args)


# =============================================================================
# CrewStructuredTool 实例
# =============================================================================

manage_tools_tool = CrewStructuredTool.from_function(
    name="manage_tools",
    description=(
        "管理 Unity MCP 工具开关状态：列出所有可用 MCP 工具及其启用状态、"
        "启用或禁用指定的 Unity MCP 工具。"
    ),
    func=_run_manage_tools,
    args_schema=ManageToolsArgs,
)

__all__ = ["ManageToolsArgs", "manage_tools_tool"]