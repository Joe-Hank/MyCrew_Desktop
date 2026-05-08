"""Unity MCP: manage_prefabs — 无头预制体操作."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManagePrefabsArgs(BaseModel):
    """manage_prefabs 参数."""
    action: str = Field(
        ...,
        description=(
            "Action:\n"
            "  get_info — 获取预制体信息 (必需: prefab_path)\n"
            "  get_hierarchy — 获取预制体层级 (必需: prefab_path)\n"
            "  create_from_gameobject — 从场景 GO 创建预制体 (必需: target, prefab_path; 可选: allow_overwrite)\n"
            "  modify_contents — 修改预制体内容 (必需: prefab_path; 可选: target, position, "
            "components_to_add, component_properties, delete_child, create_child)\n"
            "  open_prefab_stage — 打开预制体编辑模式 (必需: prefab_path)\n"
            "  save_prefab_stage — 保存当前预制体编辑\n"
            "  close_prefab_stage — 关闭预制体编辑模式"
        ),
    )
    prefab_path: str | None = Field(default=None, description="预制体资产路径，如 'Assets/Prefabs/Player.prefab'")
    target: str | None = Field(default=None, description="目标 GameObject (场景中或预制体内)")
    allow_overwrite: bool | None = Field(default=None, description="create_from_gameobject 时是否允许覆盖")
    position: list[float] | None = Field(default=None, description="modify_contents 时的位置 [x,y,z]")
    components_to_add: list[str] | None = Field(default=None, description="modify_contents 时要添加的组件")
    component_properties: dict | None = Field(
        default=None, description="modify_contents 时的组件属性: {'Rigidbody': {'mass': 5.0}}"
    )
    delete_child: str | list[str] | None = Field(
        default=None, description="modify_contents 时要删除的子对象名称或路径列表"
    )
    create_child: dict | None = Field(
        default=None,
        description="modify_contents 时创建子对象: {'name': 'SpawnPoint', 'primitive_type': 'Sphere', 'position': [0,2,0]}",
    )


def _run_manage_prefabs(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_prefabs", args)


manage_prefabs_tool = CrewStructuredTool.from_function(
    name="manage_prefabs",
    description=(
        "无头预制体操作：获取信息/层级、从场景创建预制体、修改预制体内容(添加/删除子对象、设置组件属性)、"
        "打开/保存/关闭预制体编辑模式。"
    ),
    func=_run_manage_prefabs,
    args_schema=ManagePrefabsArgs,
)

__all__ = ["ManagePrefabsArgs", "manage_prefabs_tool"]
