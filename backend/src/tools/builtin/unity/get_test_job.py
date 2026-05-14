"""Unity MCP: get_test_job — 轮询测试任务状态."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class GetTestJobArgs(BaseModel):
    """get_test_job 参数."""
    job_id: str = Field(..., description="run_tests 返回的 job_id")
    wait_timeout: int | None = Field(default=None, description="等待超时秒数")
    include_failed_tests: bool | None = Field(default=None, description="是否包含失败详情")
    include_details: bool | None = Field(default=None, description="是否包含所有测试详情")


def _run_get_test_job(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "get_test_job", args)


get_test_job_tool = CrewStructuredTool.from_function(
    name="get_test_job",
    description="轮询测试任务状态。返回 status (complete/running/failed) 和测试结果。",
    func=_run_get_test_job,
    args_schema=GetTestJobArgs,
)

__all__ = ["GetTestJobArgs", "get_test_job_tool"]
