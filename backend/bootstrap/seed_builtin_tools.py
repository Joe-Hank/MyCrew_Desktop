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
    ("read_file", "src/tools/builtin/mcp_filesystem/read_file.py"),
    ("list_directory", "src/tools/builtin/mcp_filesystem/list_directory.py"),
    ("execute_blender_code", "src/tools/builtin/mcp_blender/execute_code.py"),
    ("get_scene_info", "src/tools/builtin/mcp_blender/get_scene_info.py"),
    ("create_workflow", "src/tools/builtin/local/create_workflow.py"),
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
