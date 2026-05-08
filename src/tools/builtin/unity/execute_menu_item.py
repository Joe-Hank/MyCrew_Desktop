"""
Unity MCP: execute_menu_item — 执行任意 Unity Editor 菜单项。
"""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ExecuteMenuItemArgs(BaseModel):
    """execute_menu_item 参数."""
    menu_path: str = Field(
        ...,
        description=(
            "Unity 菜单路径，如:\n"
            "  'File/Save Project'\n"
            "  'GameObject/3D Object/Cube'\n"
            "  'Window/General/Console'"
        ),
    )


def _run_execute_menu_item(menu_path: str) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    return pool.call("unity", "execute_menu_item", {"menu_path": menu_path})


execute_menu_item_tool = CrewStructuredTool.from_function(
    name="execute_menu_item",
    description="执行任意 Unity Editor 菜单项。可用于自动化编辑器操作如创建对象、打开窗口、保存项目等。",
    func=_run_execute_menu_item,
    args_schema=ExecuteMenuItemArgs,
)

__all__ = ["ExecuteMenuItemArgs", "execute_menu_item_tool"]
