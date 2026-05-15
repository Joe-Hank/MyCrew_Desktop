"""Idempotent seeding of builtin tool rows.

Run from `bootstrap/app.py` lifespan after DB migrations. Ensures the
`tools` table has a row for each builtin tool so agents can reference
them by id in their `tool_ids` JSON array.

NB: This does NOT register the tools with CrewAI — that's done by
`crewai_runner._load_builtin_tools` at agent-construction time.
"""
from __future__ import annotations

import structlog

from infra.repo import crud

log = structlog.get_logger()

# (name, script_path_hint) — script_path is informational; not loaded
BUILTIN_TOOLS: list[tuple[str, str]] = [
    # Filesystem MCP
    ("read_file", "src/tools/builtin/mcp_filesystem/read_file.py"),
    ("list_directory", "src/tools/builtin/mcp_filesystem/list_directory.py"),
    # Blender MCP — base + extended (8 extra)
    ("execute_blender_code", "src/tools/builtin/mcp_blender/execute_code.py"),
    ("get_scene_info", "src/tools/builtin/mcp_blender/get_scene_info.py"),
    ("get_object_info", "src/tools/builtin/mcp_blender/more_tools.py"),
    ("get_viewport_screenshot", "src/tools/builtin/mcp_blender/more_tools.py"),
    ("search_polyhaven_assets", "src/tools/builtin/mcp_blender/more_tools.py"),
    ("download_polyhaven_asset", "src/tools/builtin/mcp_blender/more_tools.py"),
    ("set_texture", "src/tools/builtin/mcp_blender/more_tools.py"),
    ("generate_hyper3d_model_via_text", "src/tools/builtin/mcp_blender/more_tools.py"),
    ("poll_rodin_job_status", "src/tools/builtin/mcp_blender/more_tools.py"),
    ("import_generated_asset", "src/tools/builtin/mcp_blender/more_tools.py"),
    # ComfyUI MCP (8)
    ("comfy_create_workflow_from_template", "src/tools/builtin/mcp_comfyui/tools.py"),
    ("comfy_validate_workflow", "src/tools/builtin/mcp_comfyui/tools.py"),
    ("comfy_enqueue_workflow", "src/tools/builtin/mcp_comfyui/tools.py"),
    ("comfy_get_job_status", "src/tools/builtin/mcp_comfyui/tools.py"),
    ("comfy_get_history", "src/tools/builtin/mcp_comfyui/tools.py"),
    ("comfy_list_local_models", "src/tools/builtin/mcp_comfyui/tools.py"),
    ("comfy_list_output_images", "src/tools/builtin/mcp_comfyui/tools.py"),
    ("comfy_upload_image", "src/tools/builtin/mcp_comfyui/tools.py"),
    # Figma MCP (5)
    ("figma_get_design_context", "src/tools/builtin/mcp_figma/tools.py"),
    ("figma_get_screenshot", "src/tools/builtin/mcp_figma/tools.py"),
    ("figma_get_metadata", "src/tools/builtin/mcp_figma/tools.py"),
    ("figma_get_variable_defs", "src/tools/builtin/mcp_figma/tools.py"),
    ("figma_generate_diagram", "src/tools/builtin/mcp_figma/tools.py"),
    # Tavily MCP (3)
    ("tavily_search", "src/tools/builtin/mcp_tavily/tools.py"),
    ("tavily_extract", "src/tools/builtin/mcp_tavily/tools.py"),
    ("tavily_research", "src/tools/builtin/mcp_tavily/tools.py"),
    # Git MCP (6, factory-bound to project root)
    ("git_status", "src/tools/builtin/mcp_git/tools.py"),
    ("git_log", "src/tools/builtin/mcp_git/tools.py"),
    ("git_diff_unstaged", "src/tools/builtin/mcp_git/tools.py"),
    ("git_diff_staged", "src/tools/builtin/mcp_git/tools.py"),
    ("git_add", "src/tools/builtin/mcp_git/tools.py"),
    ("git_commit", "src/tools/builtin/mcp_git/tools.py"),
    # Plan-Maker-only (special instantiation, not loaded by generic agents)
    ("create_workflow", "src/tools/builtin/local/create_workflow.py"),
    ("assign_agents", "src/tools/builtin/local/assign_agents.py"),
    ("write_blueprint", "src/tools/builtin/local/write_blueprint.py"),
    ("patch_blueprint", "src/tools/builtin/local/patch_blueprint.py"),
    # Universal local tools — every execution agent should bind these
    ("emit_output", "src/tools/builtin/local/emit_output.py"),
    ("write_file", "src/tools/builtin/local/workspace.py"),
    ("mkdir", "src/tools/builtin/local/workspace.py"),
    ("read_file_local", "src/tools/builtin/local/workspace.py"),
    ("list_directory_local", "src/tools/builtin/local/workspace.py"),
    ("synth_8bit_sfx", "src/tools/builtin/local/synth_8bit_sfx.py"),
    # Unity MCP (34) — connects to Unity-side `MCP for Unity` bridge at
    # http://127.0.0.1:8090/mcp (override via UNITY_MCP_URL). Tool
    # instances live in src/tools/builtin/unity/__init__.TOOL_MAP and
    # are resolved in crewai_runner._load_builtin_tools.
    ("batch_execute", "src/tools/builtin/unity/batch_execute.py"),
    ("set_active_instance", "src/tools/builtin/unity/set_active_instance.py"),
    ("refresh_unity", "src/tools/builtin/unity/refresh_unity.py"),
    ("manage_tools", "src/tools/builtin/unity/manage_tools.py"),
    ("manage_scene", "src/tools/builtin/unity/manage_scene.py"),
    ("find_gameobjects", "src/tools/builtin/unity/find_gameobjects.py"),
    ("manage_gameobject", "src/tools/builtin/unity/manage_gameobject.py"),
    ("manage_components", "src/tools/builtin/unity/manage_components.py"),
    ("create_script", "src/tools/builtin/unity/create_script.py"),
    ("script_apply_edits", "src/tools/builtin/unity/script_apply_edits.py"),
    ("apply_text_edits", "src/tools/builtin/unity/apply_text_edits.py"),
    ("validate_script", "src/tools/builtin/unity/validate_script.py"),
    ("get_sha", "src/tools/builtin/unity/get_sha.py"),
    ("delete_script", "src/tools/builtin/unity/delete_script.py"),
    ("manage_asset", "src/tools/builtin/unity/manage_asset.py"),
    ("manage_prefabs", "src/tools/builtin/unity/manage_prefabs.py"),
    ("manage_material", "src/tools/builtin/unity/manage_material.py"),
    ("manage_texture", "src/tools/builtin/unity/manage_texture.py"),
    ("manage_ui", "src/tools/builtin/unity/manage_ui.py"),
    ("manage_editor", "src/tools/builtin/unity/manage_editor.py"),
    ("execute_menu_item", "src/tools/builtin/unity/execute_menu_item.py"),
    ("read_console", "src/tools/builtin/unity/read_console.py"),
    ("run_tests", "src/tools/builtin/unity/run_tests.py"),
    ("get_test_job", "src/tools/builtin/unity/get_test_job.py"),
    ("find_in_file", "src/tools/builtin/unity/find_in_file.py"),
    ("execute_custom_tool", "src/tools/builtin/unity/execute_custom_tool.py"),
    ("manage_camera", "src/tools/builtin/unity/manage_camera.py"),
    ("manage_graphics", "src/tools/builtin/unity/manage_graphics.py"),
    ("manage_packages", "src/tools/builtin/unity/manage_packages.py"),
    ("manage_physics", "src/tools/builtin/unity/manage_physics.py"),
    ("manage_probuilder", "src/tools/builtin/unity/manage_probuilder.py"),
    ("manage_profiler", "src/tools/builtin/unity/manage_profiler.py"),
    ("unity_reflect", "src/tools/builtin/unity/unity_reflect.py"),
    ("unity_docs", "src/tools/builtin/unity/unity_docs.py"),
]


async def ensure_builtin_tools() -> dict[str, str]:
    """Ensure each builtin tool has a row. Returns {name: tool_id}."""
    name_to_id: dict[str, str] = {}
    for name, script_path in BUILTIN_TOOLS:
        existing = await crud.get_all("tools", "name = ?", (name,))
        if existing:
            row = existing[0]
            name_to_id[name] = row["id"]
            continue
        row = await crud.insert("tools", {
            "name": name,
            "script_path": script_path,
            "source": "builtin",
            "params_schema": "{}",
        }, id_prefix="tool_")
        name_to_id[name] = row["id"]
        log.info("seed.builtin_tool_added", name=name, id=row["id"])
    return name_to_id
