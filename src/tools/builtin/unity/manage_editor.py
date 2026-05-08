"""
Unity MCP: manage_editor — 编辑器状态控制。

支持 8 种 action: play, pause, stop, set_timescale,
get_selection, set_selection, get_current_state, ping.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageEditorArgs(BaseModel):
    """manage_editor 参数."""
    action: str = Field(
        ...,
        description=(
            "Action to perform:\n"
            "  play — 启动 Play Mode\n"
            "  pause — 暂停 Play Mode\n"
            "  stop — 退出 Play Mode\n"
            "  set_timescale — 设置时间缩放 (必需: timescale)\n"
            "  get_selection — 获取当前选中对象列表\n"
            "  set_selection — 设置选中对象 (必需: target | targets; 可选: search_method)\n"
            "  get_current_state — 获取编辑器当前状态\n"
            "  ping — 检测可用性"
        ),
    )
    timescale: float | None = Field(default=None, description="set_timescale 时的时间缩放值")
    target: str | None = Field(default=None, description="set_selection 时的单个目标")
    targets: list[str] | None = Field(default=None, description="set_selection 时的多个目标")
    search_method: str | None = Field(
        default=None,
        description="查找方式: by_id, by_name, by_path, by_tag, by_layer, by_component",
    )


def _run_manage_editor(
    action: str,
    timescale: float | None = None,
    target: str | None = None,
    targets: list[str] | None = None,
    search_method: str | None = None,
) -> str:
    """执行 Unity MCP manage_editor."""
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool

    pool = get_unity_mcp_pool()
    args: dict[str, Any] = {"action": action}
    local_vars: dict[str, Any] = {
        "timescale": timescale, "target": target,
        "targets": targets, "search_method": search_method,
    }
    for key, value in local_vars.items():
        if value is not None:
            args[key] = value

    return pool.call("unity", "manage_editor", args)


manage_editor_tool = CrewStructuredTool.from_function(
    name="manage_editor",
    description=(
        "Unity 编辑器状态控制：启动/暂停/停止 Play Mode，设置时间缩放，"
        "获取/设置选中对象，获取编辑器当前状态。"
    ),
    func=_run_manage_editor,
    args_schema=ManageEditorArgs,
)

__all__ = ["ManageEditorArgs", "manage_editor_tool"]