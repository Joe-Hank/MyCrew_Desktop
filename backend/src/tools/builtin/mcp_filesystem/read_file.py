from typing import ClassVar

from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedMCPTool


class ReadFileArgs(BaseModel):
    path: str = Field(..., description="Absolute path of the file to read")


class ReadFile(GuardedMCPTool):
    name: str = "read_file"
    description: str = "Read the complete contents of a file from the filesystem MCP server"
    args_schema: type[BaseModel] = ReadFileArgs

    mcp_server_id: ClassVar[str] = "filesystem"
    mcp_tool_name: ClassVar[str] = "read_file"
    permission_kind: ClassVar[str | None] = "file_read"

    def _run(self, path: str) -> str:
        return self._guarded_call({"path": path})
