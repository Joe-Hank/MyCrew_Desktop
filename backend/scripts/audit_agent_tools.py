"""Audit SEED_AGENTS × tools: which tools each agent declares, which of
those actually resolve in crewai_runner._load_builtin_tools, and which
known tools are *un-assigned* to anyone (dead capacity).

Run:
    python scripts/audit_agent_tools.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def _build_known_tools_set() -> tuple[set[str], dict[str, str]]:
    """Mirror _load_builtin_tools' resolution map. Returns (names, bucket)
    where bucket[name] = 'static' / 'bound' / 'unity'.
    """
    bucket: dict[str, str] = {}

    # Static registry — direct class imports.
    # mcp_filesystem read_file / list_directory were dropped 2026-05-16
    # (the local_* variants cover the same surface; keeping both was
    # dead capacity per the audit).
    static = [
        "execute_blender_code", "get_scene_info", "get_object_info",
        "get_viewport_screenshot", "search_polyhaven_assets",
        "download_polyhaven_asset", "set_texture",
        "generate_hyper3d_model_via_text", "poll_rodin_job_status",
        "import_generated_asset",
        "comfy_create_workflow_from_template", "comfy_validate_workflow",
        "comfy_enqueue_workflow", "comfy_get_job_status", "comfy_get_history",
        "comfy_list_local_models", "comfy_list_output_images", "comfy_upload_image",
        "figma_get_design_context", "figma_get_screenshot", "figma_get_metadata",
        "figma_get_variable_defs", "figma_generate_diagram",
        "tavily_search", "tavily_extract", "tavily_research",
    ]
    for n in static:
        bucket[n] = "static"

    # Bound (context-needs) registry.
    bound = [
        "write_file", "mkdir", "read_file_local", "list_directory_local",
        "emit_output", "synth_8bit_sfx",
        "git_status", "git_log", "git_diff_unstaged", "git_diff_staged",
        "git_add", "git_commit",
    ]
    for n in bound:
        bucket[n] = "bound"

    # Unity TOOL_MAP — import to read the real set.
    try:
        from src.tools.builtin.unity import TOOL_MAP as UNITY_TOOL_MAP
        for n in UNITY_TOOL_MAP:
            bucket[n] = "unity"
    except Exception as exc:
        print(f"!! could not import UNITY_TOOL_MAP: {exc}")

    return set(bucket.keys()), bucket


def main() -> int:
    from bootstrap.seed_crews import SEED_AGENTS

    known, bucket = _build_known_tools_set()

    print(f"=== Tool resolution audit ===\n")
    print(f"Known tools in runner: {len(known)}")
    print(f"  static: {sum(1 for b in bucket.values() if b=='static')}")
    print(f"  bound : {sum(1 for b in bucket.values() if b=='bound')}")
    print(f"  unity : {sum(1 for b in bucket.values() if b=='unity')}")
    print()

    used: set[str] = set()
    agents_with_missing: list[tuple[str, list[str]]] = []

    print(f"=== {len(SEED_AGENTS)} seeded agents ===\n")
    for a in SEED_AGENTS:
        role = a["role"]
        tools = a.get("tools", [])
        missing = [t for t in tools if t not in known]
        ok = [t for t in tools if t in known]
        used.update(ok)
        flag = "OK " if not missing else "MISS"
        print(f"[{flag}] {role}  ({len(tools)} tools, {len(missing)} missing)")
        for t in tools:
            mark = "✓" if t in known else "✗"
            tag = f"({bucket.get(t, '?')})" if t in bucket else "(MISSING)"
            print(f"      {mark} {t:<40} {tag}")
        if missing:
            agents_with_missing.append((role, missing))
        print()

    print(f"=== Summary ===\n")
    print(f"Tools referenced by SEED_AGENTS but NOT resolvable in runner:")
    refs = set()
    for a in SEED_AGENTS:
        refs.update(a.get("tools", []))
    unresolved = refs - known
    if not unresolved:
        print("  (none — every declared tool resolves)")
    else:
        for n in sorted(unresolved):
            print(f"  ✗ {n}")

    print()
    print(f"Tools KNOWN to runner but NEVER assigned to any seed agent:")
    unused = known - used
    if not unused:
        print("  (none — every known tool is used somewhere)")
    else:
        for n in sorted(unused):
            print(f"  · {n}  ({bucket[n]})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
