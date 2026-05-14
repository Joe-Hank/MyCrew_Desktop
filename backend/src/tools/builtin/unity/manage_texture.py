"""Unity MCP: manage_texture — 创建程序化纹理."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageTextureArgs(BaseModel):
    """manage_texture 参数."""
    action: str = Field(
        ...,
        description=(
            "Action:\n"
            "  create — 创建纹理 (必需: path; 可选: width, height, fill_color)\n"
            "  apply_pattern — 应用图案 (必需: path, pattern; 可选: palette, pattern_size)\n"
            "  apply_gradient — 应用渐变 (必需: path; 可选: gradient_type, gradient_angle, palette)"
        ),
    )
    path: str = Field(..., description="纹理文件路径，如 'Assets/Textures/Checker.png'")
    width: int | None = Field(default=None, description="纹理宽度像素")
    height: int | None = Field(default=None, description="纹理高度像素")
    fill_color: list | None = Field(default=None, description="填充颜色 [r,g,b,a] (0-255 或 0.0-1.0)")
    pattern: str | None = Field(
        default=None, description="图案类型: checkerboard, stripes, dots, grid, brick"
    )
    palette: list | None = Field(default=None, description="调色板: [[r,g,b,a], [r,g,b,a], ...]")
    pattern_size: int | None = Field(default=None, description="图案大小")
    gradient_type: str | None = Field(default=None, description="渐变类型: linear, radial")
    gradient_angle: float | None = Field(default=None, description="线性渐变角度")


def _run_manage_texture(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_texture", args)


manage_texture_tool = CrewStructuredTool.from_function(
    name="manage_texture",
    description="创建程序化纹理：纯色填充、棋盘格/条纹/圆点/网格/砖块图案、线性/径向渐变。",
    func=_run_manage_texture,
    args_schema=ManageTextureArgs,
)

__all__ = ["ManageTextureArgs", "manage_texture_tool"]
