"""Unity MCP: manage_components — 添加、移除、设置组件属性."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageComponentsArgs(BaseModel):
    """manage_components 参数."""
    action: str = Field(
        ...,
        description=(
            "Action: add, remove, set_property.\n"
            "  add — 添加组件 (必需: target, component_type)\n"
            "  remove — 移除组件 (必需: target, component_type)\n"
            "  set_property — 设置属性 (必需: target, component_type; 用 property+value 或 properties)"
        ),
    )
    target: str | int = Field(..., description="目标 GameObject: instance ID (推荐) 或名称/路径")
    component_type: str = Field(..., description="组件类型名称，如 'Rigidbody', 'Transform', 'MyScript'")
    search_method: str | None = Field(default=None, description="查找方式: by_id, by_name, by_path")
    property: str | None = Field(default=None, description="set_property 时的单个属性名")
    value: Any | None = Field(
        default=None,
        description=(
            "set_property 时的属性值。支持多种引用格式:\n"
            "  基本值: 5.0, true, [1,2,3]\n"
            "  对象引用: {'name': 'ObjectName'}, {'instanceID': 12345}, {'path': 'Assets/...'}\n"
            "  列表引用: [{'name': 'Obj1'}, {'name': 'Obj2'}]"
        ),
    )
    properties: dict | None = Field(
        default=None, description="set_property 时的多属性字典: {'position': [1,2,3], 'localScale': [2,2,2]}"
    )


def _run_manage_components(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_components", args)


manage_components_tool = CrewStructuredTool.from_function(
    name="manage_components",
    description="添加、移除组件或设置组件属性。支持对象引用(按名称/ID/GUID/路径)。",
    func=_run_manage_components,
    args_schema=ManageComponentsArgs,
)

__all__ = ["ManageComponentsArgs", "manage_components_tool"]
