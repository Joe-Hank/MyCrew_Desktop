"""Unity MCP: manage_camera — 统一相机管理 (Unity Camera + Cinemachine)."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageCameraArgs(BaseModel):
    """manage_camera 参数."""
    action: str = Field(
        ...,
        description=(
            "Action (分层级):\n"
            "  Tier 1 (无需 Cinemachine): ping, create_camera, set_target, set_lens, "
            "set_priority, list_cameras, screenshot, screenshot_multiview\n"
            "  Tier 2 (需要 Cinemachine): ensure_brain, get_brain_status, set_body, set_aim, "
            "set_noise, add_extension, remove_extension, set_blend, force_camera, release_override"
        ),
    )
    target: str | None = Field(default=None, description="目标相机名称、路径或 instance ID")
    search_method: str | None = Field(default=None, description="查找方式: by_id, by_name, by_path")
    properties: dict | str | None = Field(
        default=None,
        description=(
            "Action 特定参数字典。常用 keys:\n"
            "  create_camera: name, preset(follow/third_person/freelook/dolly/static/top_down/side_scroller), "
            "follow, lookAt, priority, fieldOfView\n"
            "  set_body: bodyType, cameraDistance, shoulderOffset\n"
            "  set_aim: aimType\n"
            "  set_noise: amplitudeGain, frequencyGain\n"
            "  set_blend: style(Cut/EaseInOut/Linear), duration\n"
            "  add/remove_extension: extensionType\n"
            "  set_priority: priority\n"
            "  set_lens: fieldOfView, nearClipPlane, farClipPlane, orthographicSize, dutch\n"
            "  set_target: follow, lookAt\n"
            "  ensure_brain: camera, defaultBlendStyle, defaultBlendDuration"
        ),
    )
    # Screenshot params (top-level for convenience)
    capture_source: str | None = Field(default=None, description="截图来源: 'game_view' (默认) | 'scene_view'")
    camera: str | None = Field(default=None, description="截图使用的相机 (game_view 模式)")
    include_image: bool | None = Field(default=None, description="是否返回 base64 PNG 内联图像")
    max_resolution: int | None = Field(default=None, description="最大分辨率像素 (默认640)")
    batch: str | None = Field(default=None, description="批量模式: 'surround' (6角度) | 'orbit' (可配置网格)")
    view_target: str | list[float] | None = Field(
        default=None, description="截图聚焦目标: GO 名称/路径/ID 或 [x,y,z]"
    )
    view_position: list[float] | None = Field(default=None, description="相机位置 [x,y,z] (game_view)")
    view_rotation: list[float] | None = Field(default=None, description="欧拉旋转 [x,y,z] (覆盖 view_target)")
    orbit_angles: int | None = Field(default=None, description="orbit 模式方位角步数 (默认8)")
    orbit_elevations: list[float] | None = Field(default=None, description="orbit 模式仰角列表")
    orbit_distance: float | None = Field(default=None, description="orbit 模式相机距离")
    orbit_fov: float | None = Field(default=None, description="orbit 模式 FOV (默认60)")


def _run_manage_camera(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_camera", args)


manage_camera_tool = CrewStructuredTool.from_function(
    name="manage_camera",
    description=(
        "统一相机管理：创建相机(含预设)、设置目标/镜头/优先级、Cinemachine Body/Aim/Noise/扩展、"
        "截图(game_view/scene_view/surround/orbit)、Brain 控制。"
    ),
    func=_run_manage_camera,
    args_schema=ManageCameraArgs,
)

__all__ = ["ManageCameraArgs", "manage_camera_tool"]
