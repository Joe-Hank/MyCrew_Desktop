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

    # PM v5: code_contract.md — derived human-readable view of every
    # task's code contract. Written only when at least one task has a
    # non-null code_contract (so non-code projects don't pollute the
    # .mycrew dir with an empty doc). Re-generated from scratch each
    # time the blueprint is written — JSON in DB is the SSOT.
    _write_code_contract_md(base, blueprint["tasks"])

    log.info("blueprint_writer.ok",
             project_id=project["id"], dir=str(base),
             task_count=len(blueprint["tasks"]), pending=pending)
    return base, pending


def _write_code_contract_md(base: Path, tasks: list[dict]) -> None:
    """Render .mycrew/code_contract.md from per-task code_contract dicts.

    SSOT is the JSON in tasks.code_contract; this file is a derived
    human-readable view for plan review + iterate flow (the user can
    copy-paste a section back into Plan Maker to amend). Do NOT hand-
    edit — next PM run overwrites.
    """
    has_any = any(
        isinstance(t.get("code_contract"), dict) for t in tasks
    )
    target = base / "code_contract.md"
    if not has_any:
        # Clean up stale derived file from prior PM run that did have contracts
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
        return

    lines: list[str] = [
        "# 项目代码契约（PM v5 自动生成，请勿手动编辑）",
        "",
        "> 每个产 .cs 文件的 task 都在 PM Phase 5 被钉死了它要暴露的公共符号。",
        "> Crew Head **不能改**契约；Crew QA 用本文件逐条验收生成的 .cs。",
        "> 想改任何契约 → 走「迭代」流程让 PM 重跑。",
        "",
    ]
    # Collect namespace if any contract specifies one; use the most
    # common one (assumes one project = one namespace in v5 MVP).
    namespaces = [
        t["code_contract"].get("namespace")
        for t in tasks
        if isinstance(t.get("code_contract"), dict)
        and t["code_contract"].get("namespace")
    ]
    if namespaces:
        lines.extend(["## Namespace", f"`{namespaces[0]}`", ""])

    for i, t in enumerate(tasks, start=1):
        contract = t.get("code_contract")
        if not isinstance(contract, dict):
            continue
        lines.append(f"## Task {i} · {t.get('title','')}")
        for f in contract.get("files") or []:
            lines.extend([
                "",
                f"**文件**：`{f.get('path','')}`",
                "",
                "| Kind | Signature |",
                "|---|---|",
            ])
            for exp in f.get("exports") or []:
                kind = exp.get("kind", "?")
                sig = (exp.get("signature") or "").replace("|", "\\|")
                lines.append(f"| {kind} | `{sig}` |")
        imports = contract.get("imports") or []
        if imports:
            lines.extend(["", "**依赖（imports）**："])
            for imp in imports:
                from_idx = imp.get("from_task_index")
                # Translate index → human-readable task pointer; 1-based
                # for display.
                from_title = ""
                if isinstance(from_idx, int) and 0 <= from_idx < len(tasks):
                    from_title = tasks[from_idx].get("title", "")
                uses = ", ".join(f"`{u}`" for u in imp.get("uses") or [])
                lines.append(
                    f"- Task {from_idx + 1 if isinstance(from_idx, int) else '?'}"
                    f" ({from_title}) → {uses}"
                )
        lines.append("")

    try:
        target.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        # Non-fatal — the JSON column is still SSOT; just log
        log.warning("blueprint_writer.code_contract_md_failed",
                    error=str(exc))


__all__ = ["resolve_blueprint_dir", "write_blueprint_to_disk"]
