"""Unity MCP: script_apply_edits — 对 C# 脚本应用结构化编辑."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ScriptApplyEditsArgs(BaseModel):
    """script_apply_edits 参数."""
    name: str = Field(..., description="脚本名称 (不含 .cs 后缀)")
    path: str = Field(..., description="脚本所在文件夹路径，如 'Assets/Scripts'")
    edits: list[dict] = Field(
        ...,
        description=(
            "编辑操作列表，每项为一个 dict，支持的 op:\n"
            "  replace_method — {op, methodName, replacement}\n"
            "  insert_method — {op, afterMethod, code}\n"
            "  delete_method — {op, methodName}\n"
            "  anchor_insert — {op, anchor, position('before'|'after'), text}\n"
            "  regex_replace — {op, pattern, text}\n"
            "  prepend — {op, text}\n"
            "  append — {op, text}"
        ),
    )


def _run_script_apply_edits(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "script_apply_edits", args)


script_apply_edits_tool = CrewStructuredTool.from_function(
    name="script_apply_edits",
    description="对 C# 脚本应用结构化编辑（替换/插入/删除方法、锚点插入、正则替换等），比原始文本编辑更安全。",
    func=_run_script_apply_edits,
    args_schema=ScriptApplyEditsArgs,
)

__all__ = ["ScriptApplyEditsArgs", "script_apply_edits_tool"]
