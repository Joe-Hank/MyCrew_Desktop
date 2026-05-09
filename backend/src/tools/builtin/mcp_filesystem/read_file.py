from pydantic import BaseModel, Field
from crewai.tools import BaseTool

from infra.mcp.pool import mcp_pool

MCP_SERVER_ID = "filesystem"


class ReadFileArgs(BaseModel):
    path: str = Field(..., description="Absolute path of the file to read")


class ReadFile(BaseTool):
    name: str = "read_file"
    description: str = "Read the complete contents of a file from the filesystem MCP server"
    args_schema: type[BaseModel] = ReadFileArgs

    def _run(self, path: str) -> str:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            mcp_pool.call(MCP_SERVER_ID, "read_file", {"path": path})
        )
