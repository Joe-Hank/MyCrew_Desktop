"""Unity MCP: unity_reflect — 通过反射检查 Unity C# API."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class UnityReflectArgs(BaseModel):
    """unity_reflect 参数."""
    action: str = Field(
        ...,
        description=(
            "Action:\n"
            "  search — 按名称搜索类型 (必需: query; 可选: scope)\n"
            "  get_type — 获取类的成员摘要 (必需: class_name)\n"
            "  get_member — 获取成员详细签名 (必需: class_name, member_name)"
        ),
    )
    class_name: str | None = Field(default=None, description="C# 类名 (完全限定或简单名)")
    member_name: str | None = Field(default=None, description="方法/属性/字段名")
    query: str | None = Field(default=None, description="search 的搜索查询")
    scope: str | None = Field(
        default=None, description="search 的程序集范围: unity, packages, project, all (默认 unity)"
    )


def _run_unity_reflect(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "unity_reflect", args)


unity_reflect_tool = CrewStructuredTool.from_function(
    name="unity_reflect",
    description=(
        "通过反射检查 Unity 运行时 C# API。在编写引用 Unity API 的代码前务必使用此工具验证 API 存在性，"
        "避免使用过时或错误的 API。"
    ),
    func=_run_unity_reflect,
    args_schema=UnityReflectArgs,
)

__all__ = ["UnityReflectArgs", "unity_reflect_tool"]
