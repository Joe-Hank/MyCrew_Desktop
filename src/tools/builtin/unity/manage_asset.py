"""
Unity MCP: manage_asset — 资产管理（导入、创建、修改、删除、搜索）。

支持 5 种 action: import, create, modify, delete, search.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageAssetArgs(BaseModel):
    """manage_asset 参数."""
    action: str = Field(
        ...,
        description=(
            "Action to perform:\n"
            "  import — 导入资产到项目 (必需: path; 可选: source_path, destination_path, options)\n"
            "  create — 创建新资产 (必需: type; 可选: name, path, properties, content)\n"
            "  modify — 修改现有资产 (必需: target; 可选: properties)\n"
            "  delete — 删除资产 (必需: target)\n"
            "  search — 搜索资产 (可选: search_term, asset_type, folder, recursive, page_size, page_number)"
        ),
    )
    path: str | None = Field(default=None, description="import 时的源文件路径或 create 时的资产路径")
    source_path: str | None = Field(default=None, description="import 时的外部源文件路径")
    destination_path: str | None = Field(default=None, description="import 时的项目内目标路径")
    options: dict | str | None = Field(default=None, description="import 时的导入选项")
    type: str | None = Field(
        default=None,
        description=(
            "create 时的资产类型: Folder, Material, Script, Shader, Prefab, "
            "Scene, AnimatorController, AnimationClip, AudioMixer, RenderTexture, "
            "SpriteAtlas, TextAsset, AssemblyDefinitionAsset"
        ),
    )
    name: str | None = Field(default=None, description="资产名称")
    properties: dict | str | None = Field(default=None, description="modify 时的属性键值对")
    content: str | None = Field(default=None, description="create 时的文本内容（适用于 TextAsset/Script）")
    target: str | None = Field(default=None, description="modify/delete 时的目标资产路径")
    search_term: str | None = Field(default=None, description="search 时的搜索关键词")
    asset_type: str | None = Field(default=None, description="search 时按资产类型过滤")
    folder: str | None = Field(default=None, description="search 时的搜索文件夹路径")
    recursive: bool | None = Field(default=None, description="search 时是否递归搜索子文件夹")
    page_size: int | None = Field(default=None, description="search 时每页结果数")
    page_number: int | None = Field(default=None, description="search 时的页码")


def _run_manage_asset(
    action: str,
    path: str | None = None,
    source_path: str | None = None,
    destination_path: str | None = None,
    options: dict | str | None = None,
    type: str | None = None,
    name: str | None = None,
    properties: dict | str | None = None,
    content: str | None = None,
    target: str | None = None,
    search_term: str | None = None,
    asset_type: str | None = None,
    folder: str | None = None,
    recursive: bool | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
) -> str:
    """执行 Unity MCP manage_asset."""
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool

    pool = get_unity_mcp_pool()
    args: dict[str, Any] = {"action": action}

    local_vars: dict[str, Any] = {
        "path": path, "source_path": source_path, "destination_path": destination_path,
        "options": options, "type": type, "name": name, "properties": properties,
        "content": content, "target": target, "search_term": search_term,
        "asset_type": asset_type, "folder": folder, "recursive": recursive,
        "page_size": page_size, "page_number": page_number,
    }
    for key, value in local_vars.items():
        if value is not None:
            args[key] = value

    return pool.call("unity", "manage_asset", args)


manage_asset_tool = CrewStructuredTool.from_function(
    name="manage_asset",
    description=(
        "Unity 资产管理：导入外部资产、创建新资产、修改资产属性、删除资产、搜索项目中的资产。"
        "支持脚本、材质、预制体、场景等多种资产类型。"
    ),
    func=_run_manage_asset,
    args_schema=ManageAssetArgs,
)

__all__ = ["ManageAssetArgs", "manage_asset_tool"]