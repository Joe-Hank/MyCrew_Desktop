from typing import ClassVar

from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedMCPTool


class ListDirectoryArgs(BaseModel):
    path: str = Field(..., description="Absolute path of the directory to list")


class ListDirectory(GuardedMCPTool):
    name: str = "list_directory"
    description: str = "List all files and directories at the given path via the filesystem MCP server"
    args_schema: type[BaseModel] = ListDirectoryArgs

    mcp_server_id: ClassVar[str] = "filesystem"
    mcp_tool_name: ClassVar[str] = "list_directory"
    permission_kind: ClassVar[str | None] = "folder_read"

    def _run(self, path: str) -> str:
        return self._guarded_call({"path": path})
