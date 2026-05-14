"""
Unity MCP 工具集 — 通过 Unity MCP Bridge 完全控制 Unity Editor。

本包封装了 unity-mcp (beta) 官方提供的全部 34 个 MCP 工具，
以 CrewAI CrewStructuredTool 形态暴露，参数通过 Pydantic BaseModel
严格校验后透传至 Unity MCP Bridge。

使用方式：
    from src.tools.builtin.unity import ALL_TOOLS, manage_gameobject_tool

    agent = Agent(
        role="Unity 开发者",
        tools=ALL_TOOLS,  # 或选择性注册
    )
"""

from ._mcp import get_unity_mcp_pool

# Infrastructure
from .batch_execute import BatchExecuteArgs, batch_execute_tool
from .set_active_instance import SetActiveInstanceArgs, set_active_instance_tool
from .refresh_unity import RefreshUnityArgs, refresh_unity_tool
from .manage_tools import ManageToolsArgs, manage_tools_tool

# Scene
from .manage_scene import ManageSceneArgs, manage_scene_tool
from .find_gameobjects import FindGameObjectsArgs, find_gameobjects_tool

# GameObject
from .manage_gameobject import ManageGameObjectArgs, manage_gameobject_tool
from .manage_components import ManageComponentsArgs, manage_components_tool

# Script
from .create_script import CreateScriptArgs, create_script_tool
from .script_apply_edits import ScriptApplyEditsArgs, script_apply_edits_tool
from .apply_text_edits import ApplyTextEditsArgs, apply_text_edits_tool
from .validate_script import ValidateScriptArgs, validate_script_tool
from .get_sha import GetShaArgs, get_sha_tool
from .delete_script import DeleteScriptArgs, delete_script_tool

# Asset
from .manage_asset import ManageAssetArgs, manage_asset_tool
from .manage_prefabs import ManagePrefabsArgs, manage_prefabs_tool

# Material & Shader
from .manage_material import ManageMaterialArgs, manage_material_tool
from .manage_texture import ManageTextureArgs, manage_texture_tool

# UI
from .manage_ui import ManageUIArgs, manage_ui_tool

# Editor Control
from .manage_editor import ManageEditorArgs, manage_editor_tool
from .execute_menu_item import ExecuteMenuItemArgs, execute_menu_item_tool
from .read_console import ReadConsoleArgs, read_console_tool

# Testing
from .run_tests import RunTestsArgs, run_tests_tool
from .get_test_job import GetTestJobArgs, get_test_job_tool

# Search
from .find_in_file import FindInFileArgs, find_in_file_tool

# Custom
from .execute_custom_tool import ExecuteCustomToolArgs, execute_custom_tool_tool

# Camera
from .manage_camera import ManageCameraArgs, manage_camera_tool

# Graphics
from .manage_graphics import ManageGraphicsArgs, manage_graphics_tool

# Package
from .manage_packages import ManagePackagesArgs, manage_packages_tool

# Physics
from .manage_physics import ManagePhysicsArgs, manage_physics_tool

# ProBuilder
from .manage_probuilder import ManageProBuilderArgs, manage_probuilder_tool

# Profiler
from .manage_profiler import ManageProfilerArgs, manage_profiler_tool

# Docs
from .unity_reflect import UnityReflectArgs, unity_reflect_tool
from .unity_docs import UnityDocsArgs, unity_docs_tool

# ---- 工具名称映射（供 tool_registry 或动态发现使用） ----

TOOL_MAP: dict[str, object] = {
    # Infrastructure
    "batch_execute": batch_execute_tool,
    "set_active_instance": set_active_instance_tool,
    "refresh_unity": refresh_unity_tool,
    "manage_tools": manage_tools_tool,
    # Scene
    "manage_scene": manage_scene_tool,
    "find_gameobjects": find_gameobjects_tool,
    # GameObject
    "manage_gameobject": manage_gameobject_tool,
    "manage_components": manage_components_tool,
    # Script
    "create_script": create_script_tool,
    "script_apply_edits": script_apply_edits_tool,
    "apply_text_edits": apply_text_edits_tool,
    "validate_script": validate_script_tool,
    "get_sha": get_sha_tool,
    "delete_script": delete_script_tool,
    # Asset
    "manage_asset": manage_asset_tool,
    "manage_prefabs": manage_prefabs_tool,
    # Material & Shader
    "manage_material": manage_material_tool,
    "manage_texture": manage_texture_tool,
    # UI
    "manage_ui": manage_ui_tool,
    # Editor Control
    "manage_editor": manage_editor_tool,
    "execute_menu_item": execute_menu_item_tool,
    "read_console": read_console_tool,
    # Testing
    "run_tests": run_tests_tool,
    "get_test_job": get_test_job_tool,
    # Search
    "find_in_file": find_in_file_tool,
    # Custom
    "execute_custom_tool": execute_custom_tool_tool,
    # Camera
    "manage_camera": manage_camera_tool,
    # Graphics
    "manage_graphics": manage_graphics_tool,
    # Package
    "manage_packages": manage_packages_tool,
    # Physics
    "manage_physics": manage_physics_tool,
    # ProBuilder
    "manage_probuilder": manage_probuilder_tool,
    # Profiler
    "manage_profiler": manage_profiler_tool,
    # Docs
    "unity_reflect": unity_reflect_tool,
    "unity_docs": unity_docs_tool,
}

# ---- 所有工具的扁平列表（方便批量注册到 Agent） ----

ALL_TOOLS: list[object] = list(TOOL_MAP.values())

__all__ = [
    "get_unity_mcp_pool",
    "TOOL_MAP",
    "ALL_TOOLS",
    # Tool instances
    "batch_execute_tool",
    "set_active_instance_tool",
    "refresh_unity_tool",
    "manage_tools_tool",
    "manage_scene_tool",
    "find_gameobjects_tool",
    "manage_gameobject_tool",
    "manage_components_tool",
    "create_script_tool",
    "script_apply_edits_tool",
    "apply_text_edits_tool",
    "validate_script_tool",
    "get_sha_tool",
    "delete_script_tool",
    "manage_asset_tool",
    "manage_prefabs_tool",
    "manage_material_tool",
    "manage_texture_tool",
    "manage_ui_tool",
    "manage_editor_tool",
    "execute_menu_item_tool",
    "read_console_tool",
    "run_tests_tool",
    "get_test_job_tool",
    "find_in_file_tool",
    "execute_custom_tool_tool",
    "manage_camera_tool",
    "manage_graphics_tool",
    "manage_packages_tool",
    "manage_physics_tool",
    "manage_probuilder_tool",
    "manage_profiler_tool",
    "unity_reflect_tool",
    "unity_docs_tool",
    # Args schemas
    "BatchExecuteArgs",
    "SetActiveInstanceArgs",
    "RefreshUnityArgs",
    "ManageToolsArgs",
    "ManageSceneArgs",
    "FindGameObjectsArgs",
    "ManageGameObjectArgs",
    "ManageComponentsArgs",
    "CreateScriptArgs",
    "ScriptApplyEditsArgs",
    "ApplyTextEditsArgs",
    "ValidateScriptArgs",
    "GetShaArgs",
    "DeleteScriptArgs",
    "ManageAssetArgs",
    "ManagePrefabsArgs",
    "ManageMaterialArgs",
    "ManageTextureArgs",
    "ManageUIArgs",
    "ManageEditorArgs",
    "ExecuteMenuItemArgs",
    "ReadConsoleArgs",
    "RunTestsArgs",
    "GetTestJobArgs",
    "FindInFileArgs",
    "ExecuteCustomToolArgs",
    "ManageCameraArgs",
    "ManageGraphicsArgs",
    "ManagePackagesArgs",
    "ManagePhysicsArgs",
    "ManageProBuilderArgs",
    "ManageProfilerArgs",
    "UnityReflectArgs",
    "UnityDocsArgs",
]
