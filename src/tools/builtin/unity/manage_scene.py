"""
Unity MCP: manage_scene — 场景操作（加载、保存、查询等）。

支持 8 种 action: load, save, save_as, new, get_hierarchy, get_active,
get_build_settings, set_build_settings.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageSceneArgs(BaseModel):
    """manage_scene 参数."""
    action: str = Field(
        ...,
        description=(
            "Action to perform:\n"
            "  load — 加载场景 (必需: name | path)\n"
            "  save — 保存当前场景 (无额外必需参数)\n"
            "  save_as — 另存场景 (必需: path)\n"
            "  new — 创建新场景 (可选: name, path, template)\n"
            "  get_hierarchy — 获取场景层级结构 (可选: root, max_depth, include_components)\n"
            "  get_active — 获取当前活动场景信息 (无额外必需参数)\n"
            "  get_build_settings — 获取打包场景列表 (无额外必需参数)\n"
            "  set_build_settings — 设置打包场景列表 (必需: scenes)"
        ),
    )
    name: str | None = Field(default=None, description="场景名称")
    path: str | None = Field(default=None, description="场景文件路径")
    template: str | None = Field(default=None, description="new 时使用的场景模板")
    root: str | None = Field(default=None, description="get_hierarchy 时的根节点名称/路径")
    max_depth: int | None = Field(default=None, description="get_hierarchy 时的最大深度")
    include_components: bool | None = Field(default=None, description="get_hierarchy 时是否包含组件信息")
    scenes: list[str] | None = Field(default=None, description="set_build_settings 时的场景路径列表")


def _run_manage_scene(
    action: str,
    name: str | None = None,
    path: str | None = None,
    template: str | None = None,
    root: str | None = None,
    max_depth: int | None = None,
    include_components: bool | None = None,
    scenes: list[str] | None = None,
) -> str:
    """执行 Unity MCP manage_scene."""
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool

    pool = get_unity_mcp_pool()
    args: dict[str, Any] = {"action": action}
    local_vars: dict[str, Any] = {
        "name": name, "path": path, "template": template,
        "root": root, "max_depth": max_depth, "include_components": include_components,
        "scenes": scenes,
    }
    for key, value in local_vars.items():
        if value is not None:
            args[key] = value

    return pool.call("unity", "manage_scene", args)


manage_scene_tool = CrewStructuredTool.from_function(
    name="manage_scene",
    description=(
        "Unity 场景管理：加载、保存、新建场景，获取场景层级结构，"
        "管理 Build Settings 中的场景列表。"
    ),
    func=_run_manage_scene,
    args_schema=ManageSceneArgs,
)

__all__ = ["ManageSceneArgs", "manage_scene_tool"]