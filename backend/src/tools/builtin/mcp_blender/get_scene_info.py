from typing import ClassVar

from pydantic import BaseModel

from src.tools.builtin._base import GuardedMCPTool


class GetSceneInfoArgs(BaseModel):
    pass


class GetSceneInfo(GuardedMCPTool):
    name: str = "get_scene_info"
    description: str = (
        "Get information about the current Blender scene including objects, "
        "materials, and render settings"
    )
    args_schema: type[BaseModel] = GetSceneInfoArgs

    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "get_scene_info"
    # Pure inspection — no side effects
    permission_kind: ClassVar[str | None] = None

    def _run(self) -> str:
        return self._guarded_call({})
