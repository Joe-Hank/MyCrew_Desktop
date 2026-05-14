"""
Unity MCP: refresh_unity — 刷新资产数据库和触发脚本编译。
"""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class RefreshUnityArgs(BaseModel):
    """refresh_unity 参数."""
    mode: str | None = Field(
        default="if_dirty",
        description="刷新模式: 'if_dirty' (仅脏资产) | 'force' (强制全部刷新)",
    )
    scope: str | None = Field(
        default="all",
        description="刷新范围: 'assets' | 'scripts' | 'all'",
    )
    compile: str | None = Field(
        default="none",
        description="编译请求: 'none' | 'request' (请求脚本编译)",
    )
    wait_for_ready: bool | None = Field(
        default=True,
        description="是否等待编辑器就绪后再返回",
    )


def _run_refresh_unity(
    mode: str | None = "if_dirty",
    scope: str | None = "all",
    compile: str | None = "none",
    wait_for_ready: bool | None = True,
) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args: dict[str, Any] = {}
    for k, v in {"mode": mode, "scope": scope, "compile": compile, "wait_for_ready": wait_for_ready}.items():
        if v is not None:
            args[k] = v
    return pool.call("unity", "refresh_unity", args)


refresh_unity_tool = CrewStructuredTool.from_function(
    name="refresh_unity",
    description="刷新 Unity Asset Database 并触发脚本编译。修改资产或脚本后调用以同步编辑器状态。",
    func=_run_refresh_unity,
    args_schema=RefreshUnityArgs,
)

__all__ = ["RefreshUnityArgs", "refresh_unity_tool"]
