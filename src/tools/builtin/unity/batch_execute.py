"""Unity MCP: batch_execute — 批量执行多个 MCP 命令 (10-100x 更快)."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class BatchExecuteArgs(BaseModel):
    """batch_execute 参数."""
    commands: list[dict] = Field(
        ..., description="命令列表 (最多25条)，每条格式: {'tool': 'tool_name', 'params': {...}}"
    )
    parallel: bool | None = Field(default=None, description="建议并行执行 (Unity 可能仍顺序执行)")
    fail_fast: bool | None = Field(default=None, description="遇到第一个失败时停止")
    max_parallelism: int | None = Field(default=None, description="最大并行工作线程数")


def _run_batch_execute(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "batch_execute", args)


batch_execute_tool = CrewStructuredTool.from_function(
    name="batch_execute",
    description="批量执行多个 MCP 命令，比逐个调用快 10-100 倍。非事务性：前面的命令不会因后面失败而回滚。",
    func=_run_batch_execute,
    args_schema=BatchExecuteArgs,
)

__all__ = ["BatchExecuteArgs", "batch_execute_tool"]
