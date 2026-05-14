"""Unity MCP: manage_profiler — Profiler 会话/计数器/内存快照/Frame Debugger."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageProfilerArgs(BaseModel):
    """manage_profiler 参数."""
    action: str = Field(
        ...,
        description=(
            "Action 分组:\n"
            "  Session: profiler_start, profiler_stop, profiler_status, profiler_set_areas\n"
            "  Counters: get_frame_timing, get_counters, get_object_memory\n"
            "  Memory: memory_take_snapshot, memory_list_snapshots, memory_compare_snapshots\n"
            "  Frame Debugger: frame_debugger_enable, frame_debugger_disable, frame_debugger_get_events\n"
            "  Utility: ping"
        ),
    )
    category: str | None = Field(default=None, description="get_counters 的 Profiler 类别: Render, Scripts, Memory, Physics")
    counters: list[str] | None = Field(default=None, description="get_counters 的特定计数器名称列表")
    object_path: str | None = Field(default=None, description="get_object_memory 的对象路径")
    log_file: str | None = Field(default=None, description="profiler_start 的 .raw 录制文件路径")
    enable_callstacks: bool | None = Field(default=None, description="profiler_start 是否启用分配调用栈")
    areas: dict | None = Field(default=None, description="profiler_set_areas 的区域启用映射: {'CPU': true, 'GPU': true}")
    snapshot_path: str | None = Field(default=None, description="memory_take_snapshot 的输出路径")
    search_path: str | None = Field(default=None, description="memory_list_snapshots 的搜索目录")
    snapshot_a: str | None = Field(default=None, description="memory_compare_snapshots 的第一个快照路径")
    snapshot_b: str | None = Field(default=None, description="memory_compare_snapshots 的第二个快照路径")
    page_size: int | None = Field(default=None, description="frame_debugger_get_events 每页数量 (默认50)")
    cursor: int | None = Field(default=None, description="frame_debugger_get_events 游标偏移")


def _run_manage_profiler(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_profiler", args)


manage_profiler_tool = CrewStructuredTool.from_function(
    name="manage_profiler",
    description=(
        "Unity Profiler 管理：会话控制、计数器读取、内存快照对比、Frame Debugger。"
        "属于 profiling 工具组 (需通过 manage_tools 启用)。"
    ),
    func=_run_manage_profiler,
    args_schema=ManageProfilerArgs,
)

__all__ = ["ManageProfilerArgs", "manage_profiler_tool"]
