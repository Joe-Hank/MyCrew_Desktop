from typing import ClassVar

from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedMCPTool


class ExecuteBlenderCodeArgs(BaseModel):
    code: str = Field(..., description="Python code to execute in Blender's runtime")


class ExecuteBlenderCode(GuardedMCPTool):
    name: str = "execute_blender_code"
    description: str = "Execute arbitrary Python code in Blender's runtime environment"
    args_schema: type[BaseModel] = ExecuteBlenderCodeArgs

    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "execute_blender_code"
    # Arbitrary code execution → most invasive permission
    permission_kind: ClassVar[str | None] = "cmd_exec"

    def _run(self, code: str) -> str:
        return self._guarded_call({"code": code})
