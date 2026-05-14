"""Unity MCP: create_script — 创建新 C# 脚本."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class CreateScriptArgs(BaseModel):
    """create_script 参数."""
    path: str = Field(..., description="脚本路径，如 'Assets/Scripts/MyScript.cs'")
    contents: str = Field(..., description="C# 脚本完整源码")
    script_type: str | None = Field(default=None, description="脚本类型提示: MonoBehaviour, ScriptableObject 等")
    namespace: str | None = Field(default=None, description="命名空间")


def _run_create_script(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "create_script", args)


create_script_tool = CrewStructuredTool.from_function(
    name="create_script",
    description="创建新的 C# 脚本文件。指定路径和完整源码内容。",
    func=_run_create_script,
    args_schema=CreateScriptArgs,
)

__all__ = ["CreateScriptArgs", "create_script_tool"]
