"""Unity MCP: set_active_instance — 多实例工作流中路由命令到指定 Unity 实例."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class SetActiveInstanceArgs(BaseModel):
    """set_active_instance 参数."""
    instance: str = Field(..., description="Unity 实例标识: Name@hash 或 hash 前缀")


def _run_set_active_instance(instance: str) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    return pool.call("unity", "set_active_instance", {"instance": instance})


set_active_instance_tool = CrewStructuredTool.from_function(
    name="set_active_instance",
    description="多实例工作流中将后续命令路由到指定的 Unity Editor 实例。",
    func=_run_set_active_instance,
    args_schema=SetActiveInstanceArgs,
)

__all__ = ["SetActiveInstanceArgs", "set_active_instance_tool"]
