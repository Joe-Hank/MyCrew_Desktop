"""Unity MCP: get_sha — 获取文件哈希 (用于 precondition)."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class GetShaArgs(BaseModel):
    """get_sha 参数."""
    uri: str = Field(..., description="文件 URI，如 'mcpforunity://path/Assets/Scripts/MyScript.cs'")


def _run_get_sha(uri: str) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    return pool.call("unity", "get_sha", {"uri": uri})


get_sha_tool = CrewStructuredTool.from_function(
    name="get_sha",
    description="获取文件 SHA256 哈希值（不含文件内容），用于 apply_text_edits 的 precondition。",
    func=_run_get_sha,
    args_schema=GetShaArgs,
)

__all__ = ["GetShaArgs", "get_sha_tool"]
