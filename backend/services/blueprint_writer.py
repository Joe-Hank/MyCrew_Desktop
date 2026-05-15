"""Shared `.mycrew/` disk-writing logic.

Originally lived inside `write_blueprint.py` tool's `_do()`. Extracted
so PM v3's persist_svc can call the exact same writer without going
through CrewAI's tool layer, while the old iterate_existing flow keeps
calling it via the tool. **No behavioural change** for the tool path.

Layout written:
    <base>/blueprint.json       — machine-readable, full task list + meta
    <base>/architecture.md      — free-form human overview (LLM-authored)
    <base>/tasks/task_NN_<slug>.md  — per-task detail + schema + acceptance

`base` resolution mirrors what the old tool did:
    - project.root_path set → <root_path>/.mycrew[/iter-NNN]/
    - project.root_path empty → <OUTPUT_DIR>/<pid>/.mycrew_pending/
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from bootstrap.paths import OUTPUT_DIR

log = structlog.get_logger()


def resolve_blueprint_dir(project: dict) -> tuple[Path, bool]:
    """Decide where this project's .mycrew/ blueprint should live.

    Returns (base_path, is_pending). `is_pending` means root_path wasn't
    set yet — caller may want to move the dir later when the user
    configures it."""
    iteration_index = int(project.get("iteration_index") or 1)
    root_path = project.get("root_path") or ""
    if root_path:
        base = Path(root_path) / ".mycrew"
        if iteration_index > 1:
            base = base / f"iter-{iteration_index:03d}"
        return base, False
    return Path(OUTPUT_DIR) / project["id"] / ".mycrew_pending", True


def write_blueprint_to_disk(
    project: dict,
    architecture_overview: str,
    tasks: list[dict],
) -> tuple[Path, bool]:
    """Write blueprint.json + architecture.md + per-task .md files.

    Returns (base_path, is_pending). Raises on filesystem error — callers
    decide whether to surface that as a user-visible failure or roll back."""
    base, pending = resolve_blueprint_dir(project)
    base.mkdir(parents=True, exist_ok=True)
    (base / "tasks").mkdir(parents=True, exist_ok=True)

    iteration_index = int(project.get("iteration_index") or 1)

    # blueprint.json — machine-readable
    blueprint = {
        "project_id": project["id"],
        "project_name": project.get("name"),
        "iteration_index": iteration_index,
        "parent_project_id": project.get("parent_project_id"),
        "template_id": project.get("template_id"),
        "tasks": [
            t.model_dump() if hasattr(t, "model_dump") else dict(t)
            for t in tasks
        ],
    }
    (base / "blueprint.json").write_text(
        json.dumps(blueprint, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # architecture.md
    (base / "architecture.md").write_text(architecture_overview, encoding="utf-8")

    # tasks/task_NN.md
    for i, t in enumerate(blueprint["tasks"], start=1):
        slug = (t.get("title") or "task").replace("/", "_")[:40]
        fname = f"task_{i:02d}_{slug}.md"
        lines = [
            f"# Task {i}. {t.get('title','')}",
            "",
            "## 详细指令",
            t.get("detail", "(none)"),
            "",
            "## 输出 Schema",
            "```json",
            json.dumps(t.get("output_schema") or {},
                       ensure_ascii=False, indent=2),
            "```",
            "",
            "## 验收要点 (QA 读这里)",
            t.get("acceptance_notes") or "(none)",
        ]
        (base / "tasks" / fname).write_text("\n".join(lines), encoding="utf-8")

    log.info("blueprint_writer.ok",
             project_id=project["id"], dir=str(base),
             task_count=len(blueprint["tasks"]), pending=pending)
    return base, pending


__all__ = ["resolve_blueprint_dir", "write_blueprint_to_disk"]
