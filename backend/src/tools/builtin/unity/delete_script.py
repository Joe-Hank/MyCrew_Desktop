"""Unity MCP: delete_script — 删除脚本文件."""

from __future__ import annotations
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class DeleteScriptArgs(BaseModel):
    """delete_script 参数."""
    uri: str = Field(..., description="文件 URI，如 'mcpforunity://path/Assets/Scripts/OldScript.cs'")


def _run_delete_script(uri: str) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    return pool.call("unity", "delete_script", {"uri": uri})


delete_script_tool = CrewStructuredTool.from_function(
    name="delete_script",
    description="删除指定的 C# 脚本文件。",
    func=_run_delete_script,
    args_schema=DeleteScriptArgs,
)

__all__ = ["DeleteScriptArgs", "delete_script_tool"]
