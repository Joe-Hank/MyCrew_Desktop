"""Additional Blender MCP tool bridges.

The base blender-mcp server (github.com/ahujasid/blender-mcp) exposes 22
tools; this module bridges the 8 that matter most for game-asset
workflows. The remaining 14 are niche (sketchfab/hunyuan integrations,
status probes) — they can be invoked via `execute_blender_code` if
ever needed, since that one is the universal escape hatch.

Coverage:
  Scene inspection : get_object_info, get_viewport_screenshot
  Free-asset library: search_polyhaven_assets, download_polyhaven_asset
  Texturing         : set_texture
  AI generation     : generate_hyper3d_model_via_text, import_generated_asset,
                      poll_rodin_job_status
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedMCPTool


# ── Inspection ─────────────────────────────────────────────────────

class GetObjectInfoArgs(BaseModel):
    object_name: str = Field(..., description="Exact object name in the Blender scene.")


class GetObjectInfo(GuardedMCPTool):
    name: str = "get_object_info"
    description: str = "Return detailed info (transform, mesh stats, modifiers, materials) for one named Blender object."
    args_schema: type[BaseModel] = GetObjectInfoArgs
    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "get_object_info"

    def _run(self, object_name: str) -> str:
        return self._guarded_call({"object_name": object_name})


class GetViewportScreenshotArgs(BaseModel):
    max_size: int = Field(800, description="Longest edge in pixels (default 800).")


class GetViewportScreenshot(GuardedMCPTool):
    name: str = "get_viewport_screenshot"
    description: str = "Capture the current Blender viewport as a PNG (base64). Useful for visually verifying scene state before/after edits."
    args_schema: type[BaseModel] = GetViewportScreenshotArgs
    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "get_viewport_screenshot"
    permission_kind: ClassVar[str | None] = "file_read"

    def _run(self, max_size: int = 800) -> str:
        return self._guarded_call({"max_size": max_size})


# ── PolyHaven (free CC0 assets) ────────────────────────────────────

class SearchPolyhavenArgs(BaseModel):
    asset_type: str = Field("all", description='One of "all" / "hdris" / "textures" / "models".')
    categories: str | None = Field(None, description="Optional comma-separated category filter.")


class SearchPolyhavenAssets(GuardedMCPTool):
    name: str = "search_polyhaven_assets"
    description: str = "Search the PolyHaven free CC0 library for HDRIs, textures, or models."
    args_schema: type[BaseModel] = SearchPolyhavenArgs
    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "search_polyhaven_assets"

    def _run(self, asset_type: str = "all", categories: str | None = None) -> str:
        args: dict = {"asset_type": asset_type}
        if categories:
            args["categories"] = categories
        return self._guarded_call(args)


class DownloadPolyhavenArgs(BaseModel):
    asset_id: str = Field(..., description="Asset id returned by search_polyhaven_assets.")
    asset_type: str = Field(..., description='"hdris" / "textures" / "models".')
    resolution: str = Field("1k", description="Texture/HDRI resolution: 1k / 2k / 4k / 8k.")
    file_format: str | None = Field(None, description="Optional override (.hdr / .exr / .png / .jpg / .gltf / .fbx etc).")


class DownloadPolyhavenAsset(GuardedMCPTool):
    name: str = "download_polyhaven_asset"
    description: str = "Download a PolyHaven asset and import it into the current Blender scene."
    args_schema: type[BaseModel] = DownloadPolyhavenArgs
    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "download_polyhaven_asset"
    permission_kind: ClassVar[str | None] = "file_write"

    def _run(self, asset_id: str, asset_type: str,
             resolution: str = "1k", file_format: str | None = None) -> str:
        args: dict = {"asset_id": asset_id, "asset_type": asset_type, "resolution": resolution}
        if file_format:
            args["file_format"] = file_format
        return self._guarded_call(args)


# ── Texturing ──────────────────────────────────────────────────────

class SetTextureArgs(BaseModel):
    object_name: str = Field(..., description="Target Blender object to apply the texture to.")
    texture_id: str = Field(..., description="Texture asset id (typically from PolyHaven).")


class SetTexture(GuardedMCPTool):
    name: str = "set_texture"
    description: str = "Apply a downloaded PolyHaven texture to a named Blender object."
    args_schema: type[BaseModel] = SetTextureArgs
    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "set_texture"
    permission_kind: ClassVar[str | None] = "file_modify"

    def _run(self, object_name: str, texture_id: str) -> str:
        return self._guarded_call({"object_name": object_name, "texture_id": texture_id})


# ── AI 3D generation (Hyper3D Rodin) ───────────────────────────────

class GenHyper3DTextArgs(BaseModel):
    text_prompt: str = Field(..., description="Plain-text description of the model to generate.")
    bbox_condition: list[float] | None = Field(
        None,
        description="Optional [x,y,z] bounding-box hint in meters.",
    )


class GenerateHyper3DModelViaText(GuardedMCPTool):
    name: str = "generate_hyper3d_model_via_text"
    description: str = "Kick off an AI 3D-model generation job from a text prompt via Hyper3D Rodin. Returns a job id — poll with poll_rodin_job_status before import."
    args_schema: type[BaseModel] = GenHyper3DTextArgs
    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "generate_hyper3d_model_via_text"
    permission_kind: ClassVar[str | None] = "cmd_exec"

    def _run(self, text_prompt: str, bbox_condition: list[float] | None = None) -> str:
        args: dict = {"text_prompt": text_prompt}
        if bbox_condition:
            args["bbox_condition"] = bbox_condition
        return self._guarded_call(args)


class PollRodinArgs(BaseModel):
    subscription_key: str | None = Field(None, description="Polling key returned by the generation call (Hyper3D mode).")
    request_id: str | None = Field(None, description="Request id (alternate Hyper3D mode).")


class PollRodinJobStatus(GuardedMCPTool):
    name: str = "poll_rodin_job_status"
    description: str = "Poll a running Hyper3D Rodin job until it succeeds; returns status + downloadable URL."
    args_schema: type[BaseModel] = PollRodinArgs
    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "poll_rodin_job_status"

    def _run(self, subscription_key: str | None = None,
             request_id: str | None = None) -> str:
        args: dict = {}
        if subscription_key:
            args["subscription_key"] = subscription_key
        if request_id:
            args["request_id"] = request_id
        return self._guarded_call(args)


class ImportGeneratedAssetArgs(BaseModel):
    name: str = Field(..., description="Object name to assign to the imported model.")
    task_uuid: str | None = Field(None, description="Hyper3D task uuid.")
    request_id: str | None = Field(None, description="Alternate request id.")


class ImportGeneratedAsset(GuardedMCPTool):
    name: str = "import_generated_asset"
    description: str = "Import a Hyper3D-generated model (after the job is done) into the active Blender scene."
    args_schema: type[BaseModel] = ImportGeneratedAssetArgs
    mcp_server_id: ClassVar[str] = "blender"
    mcp_tool_name: ClassVar[str] = "import_generated_asset"
    permission_kind: ClassVar[str | None] = "file_write"

    def _run(self, name: str, task_uuid: str | None = None,
             request_id: str | None = None) -> str:
        args: dict = {"name": name}
        if task_uuid:
            args["task_uuid"] = task_uuid
        if request_id:
            args["request_id"] = request_id
        return self._guarded_call(args)


__all__ = [
    "GetObjectInfo",
    "GetViewportScreenshot",
    "SearchPolyhavenAssets",
    "DownloadPolyhavenAsset",
    "SetTexture",
    "GenerateHyper3DModelViaText",
    "PollRodinJobStatus",
    "ImportGeneratedAsset",
]
