from pydantic import BaseModel
from crewai.tools import BaseTool

from infra.mcp.pool import mcp_pool

MCP_SERVER_ID = "blender"


class GetSceneInfoArgs(BaseModel):
    pass


class GetSceneInfo(BaseTool):
    name: str = "get_scene_info"
    description: str = "Get information about the current Blender scene including objects, materials, and render settings"
    args_schema: type[BaseModel] = GetSceneInfoArgs

    def _run(self) -> str:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            mcp_pool.call(MCP_SERVER_ID, "get_scene_info", {})
        )
