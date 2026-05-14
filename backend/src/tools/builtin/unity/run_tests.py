"""Unity MCP: run_tests — 启动异步测试执行."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class RunTestsArgs(BaseModel):
    """run_tests 参数."""
    mode: str = Field(..., description="测试模式: 'EditMode' | 'PlayMode'")
    test_names: list[str] | None = Field(default=None, description="指定测试名称列表")
    group_names: list[str] | None = Field(default=None, description="正则匹配的测试组")
    category_names: list[str] | None = Field(default=None, description="NUnit 分类名称")
    assembly_names: list[str] | None = Field(default=None, description="程序集过滤")
    include_failed_tests: bool | None = Field(default=None, description="是否包含失败详情")
    include_details: bool | None = Field(default=None, description="是否包含所有测试详情")


def _run_run_tests(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "run_tests", args)


run_tests_tool = CrewStructuredTool.from_function(
    name="run_tests",
    description="启动异步测试执行 (EditMode/PlayMode)。返回 job_id，用 get_test_job 轮询结果。",
    func=_run_run_tests,
    args_schema=RunTestsArgs,
)

__all__ = ["RunTestsArgs", "run_tests_tool"]
