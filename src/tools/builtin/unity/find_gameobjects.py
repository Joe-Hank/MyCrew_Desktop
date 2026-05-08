"""Unity MCP: find_gameobjects — 搜索 GameObjects (返回 instance IDs)."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class FindGameObjectsArgs(BaseModel):
    """find_gameobjects 参数."""
    search_term: str = Field(..., description="搜索关键词")
    search_method: str | None = Field(
        default="by_name", description="搜索方式: by_name, by_tag, by_layer, by_component, by_path, by_id"
    )
    include_inactive: bool | None = Field(default=None, description="是否包含未激活的对象")
    page_size: int | None = Field(default=None, description="每页数量 (默认50, 最大500)")
    cursor: int | None = Field(default=None, description="分页游标")


def _run_find_gameobjects(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "find_gameobjects", args)


find_gameobjects_tool = CrewStructuredTool.from_function(
    name="find_gameobjects",
    description="搜索场景中的 GameObjects，返回 instance IDs 列表。支持按名称、标签、层、组件、路径、ID 搜索。",
    func=_run_find_gameobjects,
    args_schema=FindGameObjectsArgs,
)

__all__ = ["FindGameObjectsArgs", "find_gameobjects_tool"]
