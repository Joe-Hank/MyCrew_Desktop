"""Unity MCP: read_console — 读取或清除 Unity 控制台消息."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ReadConsoleArgs(BaseModel):
    """read_console 参数."""
    action: str = Field(
        default="get",
        description="Action: 'get' (获取消息) | 'clear' (清除控制台)",
    )
    types: list[str] | None = Field(
        default=None, description="消息类型过滤: ['error', 'warning', 'log'] 或 ['all']"
    )
    count: int | None = Field(default=None, description="最大消息数 (不使用分页时)")
    filter_text: str | None = Field(default=None, description="文本过滤关键词")
    page_size: int | None = Field(default=None, description="每页消息数")
    cursor: int | None = Field(default=None, description="分页游标")
    format: str | None = Field(default=None, description="输出格式: plain, detailed, json")
    include_stacktrace: bool | None = Field(default=None, description="是否包含堆栈跟踪")


def _run_read_console(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "read_console", args)


read_console_tool = CrewStructuredTool.from_function(
    name="read_console",
    description="读取或清除 Unity Console 消息。支持按类型/文本过滤、分页、堆栈跟踪。",
    func=_run_read_console,
    args_schema=ReadConsoleArgs,
)

__all__ = ["ReadConsoleArgs", "read_console_tool"]
