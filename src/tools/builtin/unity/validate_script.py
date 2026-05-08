"""Unity MCP: validate_script — 检查脚本语法/语义错误."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ValidateScriptArgs(BaseModel):
    """validate_script 参数."""
    uri: str = Field(..., description="文件 URI，如 'mcpforunity://path/Assets/Scripts/MyScript.cs'")
    level: str | None = Field(default="standard", description="验证级别: 'basic' | 'standard'")
    include_diagnostics: bool | None = Field(default=None, description="是否包含完整错误详情")


def _run_validate_script(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "validate_script", args)


validate_script_tool = CrewStructuredTool.from_function(
    name="validate_script",
    description="检查 C# 脚本的语法和语义错误，返回诊断信息。",
    func=_run_validate_script,
    args_schema=ValidateScriptArgs,
)

__all__ = ["ValidateScriptArgs", "validate_script_tool"]
