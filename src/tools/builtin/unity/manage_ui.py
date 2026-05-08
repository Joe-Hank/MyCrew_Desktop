"""Unity MCP: manage_ui — UI Toolkit 管理 (UXML, USS, UIDocument)."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageUIArgs(BaseModel):
    """manage_ui 参数."""
    action: str = Field(
        ...,
        description=(
            "Action:\n"
            "  create — 创建 UXML/USS 文件 (必需: path, contents)\n"
            "  read — 读取 UXML/USS 文件 (必需: path)\n"
            "  update — 更新 UXML/USS 文件 (必需: path, contents)\n"
            "  attach_ui_document — 附加 UIDocument 到 GO (必需: target, source_asset; 可选: panel_settings, sort_order)\n"
            "  create_panel_settings — 创建 PanelSettings 资产 (必需: path; 可选: scale_mode, reference_resolution)\n"
            "  get_visual_tree — 检查 UIDocument 的 VisualTree (必需: target; 可选: max_depth)"
        ),
    )
    path: str | None = Field(default=None, description="UXML/USS/PanelSettings 文件路径")
    contents: str | None = Field(default=None, description="UXML/USS 文件内容")
    target: str | None = Field(default=None, description="目标 GameObject 名称/路径")
    source_asset: str | None = Field(default=None, description="attach 时的 UXML 源资产路径")
    panel_settings: str | None = Field(default=None, description="PanelSettings 资产路径 (省略则自动创建)")
    sort_order: int | None = Field(default=None, description="UIDocument 排序顺序")
    scale_mode: str | None = Field(
        default=None, description="缩放模式: ConstantPixelSize, ConstantPhysicalSize, ScaleWithScreenSize"
    )
    reference_resolution: dict | None = Field(
        default=None, description="参考分辨率: {'width': 1920, 'height': 1080}"
    )
    max_depth: int | None = Field(default=None, description="get_visual_tree 的最大深度 (默认10)")


def _run_manage_ui(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_ui", args)


manage_ui_tool = CrewStructuredTool.from_function(
    name="manage_ui",
    description=(
        "Unity UI Toolkit 管理：创建/读取/更新 UXML 和 USS 文件，附加 UIDocument 到 GameObject，"
        "创建 PanelSettings，检查 VisualTree 层级。"
    ),
    func=_run_manage_ui,
    args_schema=ManageUIArgs,
)

__all__ = ["ManageUIArgs", "manage_ui_tool"]
