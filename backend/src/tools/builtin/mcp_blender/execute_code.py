from pydantic import BaseModel, Field
from crewai.tools import BaseTool

from infra.mcp.pool import mcp_pool

MCP_SERVER_ID = "blender"


class ExecuteBlenderCodeArgs(BaseModel):
    code: str = Field(..., description="Python code to execute in Blender's runtime")


class ExecuteBlenderCode(BaseTool):
    name: str = "execute_blender_code"
    description: str = "Execute arbitrary Python code in Blender's runtime environment"
    args_schema: type[BaseModel] = ExecuteBlenderCodeArgs

    def _run(self, code: str) -> str:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            mcp_pool.call(MCP_SERVER_ID, "execute_blender_code", {"code": code})
        )
