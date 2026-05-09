from pydantic import BaseModel, Field
from crewai.tools import BaseTool

from infra.mcp.pool import mcp_pool

MCP_SERVER_ID = "filesystem"


class ListDirectoryArgs(BaseModel):
    path: str = Field(..., description="Absolute path of the directory to list")


class ListDirectory(BaseTool):
    name: str = "list_directory"
    description: str = "List all files and directories at the given path via the filesystem MCP server"
    args_schema: type[BaseModel] = ListDirectoryArgs

    def _run(self, path: str) -> str:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            mcp_pool.call(MCP_SERVER_ID, "list_directory", {"path": path})
        )
