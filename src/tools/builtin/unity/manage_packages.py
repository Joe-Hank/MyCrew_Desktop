"""Unity MCP: manage_packages — UPM 包管理."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManagePackagesArgs(BaseModel):
    """manage_packages 参数."""
    action: str = Field(
        ...,
        description=(
            "Action:\n"
            "  Query: list_packages, search_packages, get_package_info, list_registries, ping, status\n"
            "  Mutating: add_package, remove_package, embed_package, resolve_packages, "
            "add_registry, remove_registry"
        ),
    )
    package: str | None = Field(default=None, description="包名/ID，如 'com.unity.inputsystem' 或 'com.unity.cinemachine@3.1.6'")
    query: str | None = Field(default=None, description="search_packages 的搜索关键词")
    job_id: str | None = Field(default=None, description="status 轮询的 job_id")
    force: bool | None = Field(default=None, description="remove_package 时强制移除 (忽略依赖)")
    name: str | None = Field(default=None, description="add_registry 的注册表名称")
    url: str | None = Field(default=None, description="add_registry 的注册表 URL")
    scopes: list[str] | None = Field(default=None, description="add_registry 的作用域列表")


def _run_manage_packages(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_packages", args)


manage_packages_tool = CrewStructuredTool.from_function(
    name="manage_packages",
    description=(
        "Unity 包管理：列出/搜索/安装/移除/嵌入 UPM 包，管理 Scoped Registry。"
        "安装/移除会触发 domain reload。"
    ),
    func=_run_manage_packages,
    args_schema=ManagePackagesArgs,
)

__all__ = ["ManagePackagesArgs", "manage_packages_tool"]
