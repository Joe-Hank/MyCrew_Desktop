"""Unity MCP: manage_graphics — 渲染/后处理/光照烘焙/管线/URP Features."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageGraphicsArgs(BaseModel):
    """manage_graphics 参数."""
    action: str = Field(
        ...,
        description=(
            "Action 分组:\n"
            "  Status: ping\n"
            "  Volume: volume_create, volume_add_effect, volume_set_effect, volume_remove_effect, "
            "volume_get_info, volume_set_properties, volume_list_effects, volume_create_profile\n"
            "  Bake: bake_start, bake_cancel, bake_status, bake_clear, bake_reflection_probe, "
            "bake_get_settings, bake_set_settings, bake_create_light_probe_group, "
            "bake_create_reflection_probe, bake_set_probe_positions\n"
            "  Stats: stats_get, stats_list_counters, stats_set_scene_debug, stats_get_memory\n"
            "  Pipeline: pipeline_get_info, pipeline_set_quality, pipeline_get_settings, pipeline_set_settings\n"
            "  Features (URP): feature_list, feature_add, feature_remove, feature_configure, "
            "feature_toggle, feature_reorder"
        ),
    )
    target: str | None = Field(default=None, description="目标对象名称或 instance ID")
    effect: str | None = Field(default=None, description="效果类型名，如 'Bloom', 'Vignette'")
    properties: dict | None = Field(default=None, description="Volume/Feature 属性字典")
    parameters: dict | None = Field(default=None, description="效果参数字典")
    settings: dict | None = Field(default=None, description="Bake/Pipeline 设置字典")
    name: str | None = Field(default=None, description="创建对象的名称")
    profile_path: str | None = Field(default=None, description="VolumeProfile 资产路径")
    path: str | None = Field(default=None, description="volume_create_profile 的资产路径")
    position: list[float] | None = Field(default=None, description="位置 [x,y,z]")
    effects: list[dict] | None = Field(
        default=None, description="volume_create/volume_create_profile 的效果列表"
    )
    is_global: bool | None = Field(default=None, description="volume_create 是否全局")
    weight: float | None = Field(default=None, description="Volume 权重 0-1")
    priority: int | None = Field(default=None, description="Volume 优先级")
    async_bake: bool | None = Field(default=None, description="bake_start 是否异步")
    grid_size: list | None = Field(default=None, description="Light Probe Group 网格大小 [x,y,z]")
    spacing: float | None = Field(default=None, description="Light Probe 间距")
    size: list[float] | None = Field(default=None, description="Reflection Probe 尺寸 [x,y,z]")
    resolution: int | None = Field(default=None, description="Reflection Probe 分辨率")
    mode: str | None = Field(default=None, description="Probe 模式 / Scene debug mode")
    hdr: bool | None = Field(default=None, description="Reflection Probe HDR")
    box_projection: bool | None = Field(default=None, description="Reflection Probe Box Projection")
    positions: list | None = Field(default=None, description="bake_set_probe_positions 的位置数组")
    level: str | int | None = Field(default=None, description="pipeline_set_quality 的质量级别")
    feature_type: str | None = Field(default=None, description="feature_add 的特性类型")
    material: str | None = Field(default=None, description="feature_add 的材质路径")
    index: int | None = Field(default=None, description="feature 索引")
    active: bool | None = Field(default=None, description="feature_toggle 启用/禁用")
    order: list[int] | None = Field(default=None, description="feature_reorder 的顺序列表")


def _run_manage_graphics(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_graphics", args)


manage_graphics_tool = CrewStructuredTool.from_function(
    name="manage_graphics",
    description=(
        "统一渲染和图形管理：Volume 后处理、光照烘焙、渲染统计、管线配置、URP Renderer Features。"
        "需要 URP/HDRP 才能使用 Volume/Feature 功能。"
    ),
    func=_run_manage_graphics,
    args_schema=ManageGraphicsArgs,
)

__all__ = ["ManageGraphicsArgs", "manage_graphics_tool"]
