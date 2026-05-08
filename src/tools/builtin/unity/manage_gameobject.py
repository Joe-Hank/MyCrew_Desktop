"""
Unity MCP: manage_gameobject — Create, modify, delete, duplicate GameObjects.

Actions: create, modify, delete, duplicate, move_relative, look_at.
"""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageGameObjectArgs(BaseModel):
    """manage_gameobject 参数 — 严格匹配官方文档."""
    action: str = Field(
        ...,
        description=(
            "Action to perform:\n"
            "  create — 创建 GameObject (可选: name, primitive_type, prefab_path, position, rotation, scale, "
            "parent, components_to_add, save_as_prefab, prefab_path)\n"
            "  modify — 修改 GameObject (必需: target; 可选: search_method, position, rotation, scale, "
            "set_active, layer, components_to_add, components_to_remove, component_properties)\n"
            "  delete — 删除 (必需: target; 可选: search_method)\n"
            "  duplicate — 复制 (必需: target; 可选: new_name, offset, search_method)\n"
            "  move_relative — 相对移动 (必需: target; 可选: reference_object, direction, distance, world_space)\n"
            "  look_at — 旋转朝向目标 (必需: target, look_at_target; 可选: look_at_up)"
        ),
    )
    target: str | int | None = Field(default=None, description="目标 GameObject 名称、路径或 instance ID")
    search_method: str | None = Field(
        default=None, description="查找方式: by_name, by_tag, by_layer, by_component, by_path, by_id"
    )
    # create params
    name: str | None = Field(default=None, description="GameObject 名称")
    primitive_type: str | None = Field(
        default=None, description="原始体类型: Cube, Sphere, Capsule, Cylinder, Plane, Quad"
    )
    prefab_path: str | None = Field(
        default=None, description="预制体路径 (create 时实例化预制体; 也用于 save_as_prefab 的保存路径)"
    )
    position: list[float] | str | None = Field(default=None, description="世界坐标 [x,y,z] 或 JSON 字符串")
    rotation: list[float] | str | None = Field(default=None, description="欧拉角 [x,y,z]")
    scale: list[float] | str | None = Field(default=None, description="缩放 [x,y,z]")
    parent: str | None = Field(default=None, description="父级 GameObject 名称/路径")
    components_to_add: list[str] | None = Field(default=None, description="要添加的组件类型列表")
    save_as_prefab: bool | None = Field(default=None, description="create 时是否同时保存为预制体")
    # modify params
    set_active: bool | None = Field(default=None, description="设置 active 状态")
    layer: str | None = Field(default=None, description="设置 Layer")
    components_to_remove: list[str] | None = Field(default=None, description="要移除的组件类型列表")
    component_properties: dict | str | None = Field(
        default=None,
        description="组件属性设置，嵌套字典格式: {'Rigidbody': {'mass': 10.0, 'useGravity': True}}",
    )
    # duplicate params
    new_name: str | None = Field(default=None, description="duplicate 时的新名称")
    offset: list[float] | None = Field(default=None, description="duplicate 时的位置偏移 [x,y,z]")
    # move_relative params
    reference_object: str | None = Field(default=None, description="move_relative 的参考对象")
    direction: str | None = Field(
        default=None, description="移动方向: left, right, up, down, forward, back"
    )
    distance: float | None = Field(default=None, description="移动距离")
    world_space: bool | None = Field(default=None, description="是否使用世界坐标系")
    # look_at params
    look_at_target: str | list[float] | None = Field(
        default=None, description="look_at 的目标: GO 名称/路径 或 世界坐标 [x,y,z]"
    )
    look_at_up: list[float] | None = Field(default=None, description="look_at 的 up 向量，默认 [0,1,0]")


def _run_manage_gameobject(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_gameobject", args)


manage_gameobject_tool = CrewStructuredTool.from_function(
    name="manage_gameobject",
    description=(
        "Unity GameObject 操作：创建(含预制体实例化)、修改属性和组件、删除、复制、"
        "相对移动、旋转朝向目标。是场景操作的核心工具。"
    ),
    func=_run_manage_gameobject,
    args_schema=ManageGameObjectArgs,
)

__all__ = ["ManageGameObjectArgs", "manage_gameobject_tool"]
