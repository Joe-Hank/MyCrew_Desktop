"""Unity MCP: apply_text_edits — 精确字符位置编辑 (1-indexed lines/columns)."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ApplyTextEditsArgs(BaseModel):
    """apply_text_edits 参数."""
    uri: str = Field(..., description="文件 URI，如 'mcpforunity://path/Assets/Scripts/MyScript.cs'")
    edits: list[dict] = Field(
        ...,
        description=(
            "编辑列表，每项: {startLine, startCol, endLine, endCol, newText}。"
            "行列号均为 1-indexed。"
        ),
    )
    precondition_sha256: str | None = Field(default=None, description="文件 SHA256 前置条件，防止过期编辑")
    strict: bool | None = Field(default=None, description="是否启用严格验证模式")


def _run_apply_text_edits(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "apply_text_edits", args)


apply_text_edits_tool = CrewStructuredTool.from_function(
    name="apply_text_edits",
    description="对文件应用精确的字符位置编辑 (1-indexed 行列号)。支持 SHA256 前置条件防止并发冲突。",
    func=_run_apply_text_edits,
    args_schema=ApplyTextEditsArgs,
)

__all__ = ["ApplyTextEditsArgs", "apply_text_edits_tool"]
