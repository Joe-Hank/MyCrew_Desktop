"""Unity MCP: find_in_file — 正则搜索文件内容."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class FindInFileArgs(BaseModel):
    """find_in_file 参数."""
    uri: str = Field(..., description="文件 URI，如 'mcpforunity://path/Assets/Scripts/MyScript.cs'")
    pattern: str = Field(..., description="正则表达式模式")
    max_results: int | None = Field(default=None, description="最大结果数 (默认200)")
    ignore_case: bool | None = Field(default=None, description="是否忽略大小写")


def _run_find_in_file(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "find_in_file", args)


find_in_file_tool = CrewStructuredTool.from_function(
    name="find_in_file",
    description="用正则表达式搜索文件内容，返回行号、内容摘录和匹配位置。",
    func=_run_find_in_file,
    args_schema=FindInFileArgs,
)

__all__ = ["FindInFileArgs", "find_in_file_tool"]
