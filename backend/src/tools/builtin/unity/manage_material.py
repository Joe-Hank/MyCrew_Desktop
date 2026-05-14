"""Unity MCP: manage_material — 创建和修改材质."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageMaterialArgs(BaseModel):
    """manage_material 参数."""
    action: str = Field(
        ...,
        description=(
            "Action:\n"
            "  create — 创建材质 (必需: material_path; 可选: shader, properties)\n"
            "  get_material_info — 获取材质信息 (必需: material_path)\n"
            "  set_material_shader_property — 设置 shader 属性 (必需: material_path, property, value)\n"
            "  set_material_color — 设置颜色 (必需: material_path, property, color)\n"
            "  assign_material_to_renderer — 分配材质到渲染器 (必需: target, material_path; 可选: slot)\n"
            "  set_renderer_color — 直接设置渲染器颜色 (必需: target, color; 可选: mode)"
        ),
    )
    material_path: str | None = Field(default=None, description="材质资产路径，如 'Assets/Materials/Red.mat'")
    shader: str | None = Field(default=None, description="create 时的 Shader 名称，如 'Standard', 'Universal Render Pipeline/Lit'")
    properties: dict | None = Field(default=None, description="create 时的属性字典: {'_Color': [1,0,0,1]}")
    property: str | None = Field(default=None, description="属性名，如 '_Metallic', '_BaseColor'")
    value: Any | None = Field(default=None, description="set_material_shader_property 时的属性值")
    color: list[float] | None = Field(default=None, description="RGBA 颜色值 [r,g,b,a]")
    target: str | None = Field(default=None, description="目标 GameObject 名称/路径")
    slot: int | None = Field(default=None, description="assign_material_to_renderer 时的材质槽索引")
    mode: str | None = Field(
        default=None,
        description=(
            "set_renderer_color 的模式:\n"
            "  'property_block' (默认, 非持久)\n"
            "  'create_unique' (创建唯一 .mat 资产, 持久)\n"
            "  'shared' (修改共享材质)\n"
            "  'instance' (仅运行时)"
        ),
    )


def _run_manage_material(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_material", args)


manage_material_tool = CrewStructuredTool.from_function(
    name="manage_material",
    description="创建和修改 Unity 材质：创建材质、获取信息、设置 shader 属性/颜色、分配到渲染器。",
    func=_run_manage_material,
    args_schema=ManageMaterialArgs,
)

__all__ = ["ManageMaterialArgs", "manage_material_tool"]
