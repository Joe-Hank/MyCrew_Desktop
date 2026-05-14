"""Unity MCP: unity_docs — 获取 Unity 官方文档."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class UnityDocsArgs(BaseModel):
    """unity_docs 参数."""
    action: str = Field(
        ...,
        description=(
            "Action:\n"
            "  get_doc — 获取 ScriptReference 文档 (必需: class_name; 可选: member_name, version)\n"
            "  get_manual — 获取 Manual 页面 (必需: slug; 可选: version)\n"
            "  get_package_doc — 获取包文档 (必需: package, page; 可选: pkg_version)\n"
            "  lookup — 并行搜索多个文档源 (必需: query 或 queries; 可选: package, pkg_version)"
        ),
    )
    class_name: str | None = Field(default=None, description="Unity 类名，如 'Physics', 'Transform'")
    member_name: str | None = Field(default=None, description="方法/属性名")
    version: str | None = Field(default=None, description="Unity 版本，如 '6000.0.38f1'")
    slug: str | None = Field(default=None, description="Manual 页面 slug，如 'execution-order'")
    package: str | None = Field(default=None, description="包名，如 'com.unity.render-pipelines.universal'")
    page: str | None = Field(default=None, description="包文档页面，如 'index', '2d-index'")
    pkg_version: str | None = Field(default=None, description="包版本 major.minor，如 '17.0'")
    query: str | None = Field(default=None, description="lookup 单个查询")
    queries: str | None = Field(default=None, description="lookup 批量查询 (逗号分隔)，如 'Physics.Raycast,NavMeshAgent'")


def _run_unity_docs(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "unity_docs", args)


unity_docs_tool = CrewStructuredTool.from_function(
    name="unity_docs",
    description=(
        "获取 Unity 官方文档：ScriptReference、Manual、包文档。"
        "支持批量 lookup 并行搜索。用于验证 API 用法和获取代码示例。"
    ),
    func=_run_unity_docs,
    args_schema=UnityDocsArgs,
)

__all__ = ["UnityDocsArgs", "unity_docs_tool"]
