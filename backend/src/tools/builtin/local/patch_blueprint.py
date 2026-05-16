"""PatchBlueprintTool — surgical edits on a draft project's task list.

Used by the `modify_blueprint` sub-agent when the user asks for small
changes ("add a boss task" / "delete the BGM one" / "change task 3
title"). Only operates on projects in state='ready' with no tasks yet
executed; mutations on running/completed projects are refused.

session_id is bound via factory at instantiation. The agent doesn't
have to (and shouldn't) supply session id.

Supported ops (each is a dict in the `ops` list):

  {"op": "add_task", "title": "...", "detail": "...", "deps": [],
   "output_schema": {...}, "kind": "regular", "after_index": 2 | null}
  {"op": "remove_task", "task_id": "task_xxx"}
  {"op": "remove_task", "task_index": 3}              (0-based)
  {"op": "update_task", "task_id": "task_xxx", "patch": {"title": "..."}}
  {"op": "update_task", "task_index": 3, "patch": {...}}
  {"op": "reorder", "order": ["task_xxx", "task_yyy", ...]}
  {"op": "assign_agent", "task_id": "task_xxx", "agent_id": "agent_yyy"}
"""
from __future__ import annotations

import json
from typing import Any, ClassVar

import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool

log = structlog.get_logger()


class PatchBlueprintArgs(BaseModel):
    ops: list[dict] = Field(
        ...,
        description=(
            "Ordered list of edit ops. Each op is a dict with 'op' field, "
            "see tool docstring for shape. Applied in sequence; first "
            "failure stops the rest."
        ),
    )


class PatchBlueprintTool(GuardedLocalTool):
    name: str = "patch_blueprint"
    description: str = (
        "Apply small edits to the current project's DRAFT task list. "
        "Only works on state='ready' projects with no tasks executed yet. "
        "Ops: add_task / remove_task / update_task / reorder / assign_agent. "
        "Returns a summary of what was changed."
    )
    args_schema: type[BaseModel] = PatchBlueprintArgs
    permission_kind: ClassVar[str | None] = "workflow_create"

    _bound_session_id: ClassVar[str] = ""

    def _run(self, ops: list[dict]) -> str:
        session_id = self._bound_session_id
        if not session_id:
            return "[Error] Internal: session_id not bound."
        if not isinstance(ops, list) or not ops:
            return "[Error] ops must be a non-empty list."

        async def _do() -> str:
            from infra.repo import crud

            session = await crud.get_by_id("inception_sessions", session_id)
            if not session or not session.get("project_id"):
                return "[Error] No project bound to this session."
            project_id = session["project_id"]

            project = await crud.get_by_id("projects", project_id)
            if not project:
                return f"[Error] Project {project_id} not found."

            # Guard: only modify draft projects (ready + nothing executed)
            if project.get("state") != "ready":
                return (
                    f"[Refused] Project state is {project.get('state')!r}; "
                    "patch_blueprint only works on state='ready' (draft)."
                )
            if project.get("is_running"):
                return "[Refused] Project is running."

            tasks = await crud.get_all(
                "tasks", "project_id = ?", (project_id,),
            )
            tasks_by_id = {t["id"]: t for t in tasks}
            ordered_ids = [t["id"] for t in tasks]
            done_count = sum(1 for t in tasks if t.get("status") == "done")
            if done_count > 0:
                return (
                    f"[Refused] Project has {done_count} completed task(s); "
                    "patch_blueprint cannot edit projects with executed tasks."
                )

            summary: list[str] = []
            for i, op_dict in enumerate(ops):
                if not isinstance(op_dict, dict):
                    return f"[Error] op {i} is not a dict."
                op = op_dict.get("op")
                try:
                    if op == "add_task":
                        new = await _do_add_task(project_id, op_dict, ordered_ids)
                        ordered_ids = new["ordered"]
                        summary.append(new["msg"])
                    elif op == "remove_task":
                        new = await _do_remove_task(op_dict, tasks_by_id, ordered_ids)
                        ordered_ids = new["ordered"]
                        summary.append(new["msg"])
                    elif op == "update_task":
                        msg = await _do_update_task(op_dict, tasks_by_id, ordered_ids)
                        summary.append(msg)
                    elif op == "reorder":
                        msg = _do_reorder(op_dict, tasks_by_id)
                        # ordered_ids stays a model of "new desired order"
                        ordered_ids = list(op_dict.get("order") or [])
                        summary.append(msg)
                    elif op == "assign_agent":
                        msg = await _do_assign_agent(op_dict, tasks_by_id, ordered_ids)
                        summary.append(msg)
                    else:
                        summary.append(f"  · skip op {i}: unknown op {op!r}")
                except Exception as exc:  # noqa: BLE001
                    return f"[Error] op {i} ({op}) failed: {exc}"

            # Bonus: refresh .mycrew/blueprint.json to reflect new state
            await _refresh_mycrew_blueprint(project_id)

            log.info("patch_blueprint.applied",
                     project_id=project_id, op_count=len(ops))
            return "Applied:\n" + "\n".join(summary)

        try:
            return self._guarded_local(_do)
        except Exception as exc:  # noqa: BLE001
            log.error("patch_blueprint.failed", error=str(exc),
                      session_id=session_id)
            return f"[Error] patch_blueprint failed: {exc}"


# ── Op handlers (free functions for clarity) ─────────────────────────

async def _do_add_task(
    project_id: str, op: dict, ordered_ids: list[str],
) -> dict[str, Any]:
    from infra.repo import crud

    title = op.get("title") or "新任务"
    detail = op.get("detail") or ""
    deps = op.get("deps") or []
    output_schema = op.get("output_schema") or {}
    kind = op.get("kind") or "regular"
    after_index = op.get("after_index")

    row = await crud.insert("tasks", {
        "project_id": project_id,
        "title": title,
        "detail": detail,
        "kind": kind,
        "output_schema": json.dumps(output_schema, ensure_ascii=False),
        "status": "pending",
        "deps": json.dumps(deps, ensure_ascii=False),
        "agent_id": None,
    }, id_prefix="task_")
    new_id = row["id"]

    new_ordered = list(ordered_ids)
    if isinstance(after_index, int) and 0 <= after_index < len(new_ordered):
        new_ordered.insert(after_index + 1, new_id)
    else:
        new_ordered.append(new_id)
    return {
        "ordered": new_ordered,
        "msg": f"  · add_task: {title!r} → {new_id[:14]}",
    }


async def _do_remove_task(
    op: dict, tasks_by_id: dict[str, dict], ordered_ids: list[str],
) -> dict[str, Any]:
    from infra.repo import crud

    task_id = _resolve_task_id(op, ordered_ids)
    if not task_id or task_id not in tasks_by_id:
        return {
            "ordered": ordered_ids,
            "msg": f"  · skip remove: task not found ({op})",
        }
    title = tasks_by_id[task_id].get("title", "?")
    await crud.delete_by_id("tasks", task_id)
    new_ordered = [tid for tid in ordered_ids if tid != task_id]
    # Also strip this id from other tasks' deps arrays
    for tid in new_ordered:
        t = tasks_by_id.get(tid)
        if not t:
            continue
        deps_raw = t.get("deps") or "[]"
        try:
            deps = json.loads(deps_raw) if isinstance(deps_raw, str) else (deps_raw or [])
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("patch_blueprint.deps_decode_failed",
                        task_id=tid, error=str(exc))
            deps = []
        if task_id in deps:
            deps = [d for d in deps if d != task_id]
            await crud.update_by_id("tasks", tid, {
                "deps": json.dumps(deps, ensure_ascii=False),
            })
    return {
        "ordered": new_ordered,
        "msg": f"  · remove_task: {title!r}",
    }


async def _do_update_task(
    op: dict, tasks_by_id: dict[str, dict], ordered_ids: list[str],
) -> str:
    from infra.repo import crud

    task_id = _resolve_task_id(op, ordered_ids)
    if not task_id or task_id not in tasks_by_id:
        return f"  · skip update: task not found ({op})"
    patch = op.get("patch") or {}
    if not isinstance(patch, dict) or not patch:
        return f"  · skip update: empty patch for {task_id[:14]}"

    # Serialize known JSON fields
    norm_patch: dict[str, Any] = {}
    for k, v in patch.items():
        if k in ("output_schema", "deps"):
            norm_patch[k] = json.dumps(v, ensure_ascii=False)
        else:
            norm_patch[k] = v
    await crud.update_by_id("tasks", task_id, norm_patch)
    fields = ", ".join(patch.keys())
    return f"  · update_task: {task_id[:14]} ({fields})"


def _do_reorder(op: dict, tasks_by_id: dict[str, dict]) -> str:
    new_order = op.get("order") or []
    if not isinstance(new_order, list) or not new_order:
        return "  · skip reorder: order is not a list"
    # We don't actually have a column to store order — task ordering is by
    # DB rowid (insertion order). For now this op is a no-op; future:
    # add an `order_index` column. Mark as "advisory".
    return (
        f"  · reorder noted: {len(new_order)} ids (advisory only — "
        "tasks table has no order column yet)"
    )


async def _do_assign_agent(
    op: dict, tasks_by_id: dict[str, dict], ordered_ids: list[str],
) -> str:
    from infra.repo import crud

    task_id = _resolve_task_id(op, ordered_ids)
    if not task_id or task_id not in tasks_by_id:
        return f"  · skip assign: task not found ({op})"
    agent_id = op.get("agent_id")
    if not agent_id:
        return f"  · skip assign: missing agent_id"
    found = await crud.get_by_id("agents", agent_id)
    if not found:
        return f"  · skip assign: agent {agent_id} not found"
    await crud.update_by_id("tasks", task_id, {"agent_id": agent_id})
    return f"  · assign_agent: {task_id[:14]} → {found.get('role','?')}"


def _resolve_task_id(op: dict, ordered_ids: list[str]) -> str | None:
    tid = op.get("task_id")
    if isinstance(tid, str) and tid:
        return tid
    idx = op.get("task_index")
    if isinstance(idx, int) and 0 <= idx < len(ordered_ids):
        return ordered_ids[idx]
    return None


async def _refresh_mycrew_blueprint(project_id: str) -> None:
    """Re-derive .mycrew/blueprint.json from current DB state. Best-effort."""
    from pathlib import Path
    from infra.repo import crud

    project = await crud.get_by_id("projects", project_id)
    if not project:
        return
    root = project.get("root_path") or ""
    if not root:
        return

    iter_idx = int(project.get("iteration_index") or 1)
    base = Path(root) / ".mycrew"
    if iter_idx > 1:
        base = base / f"iter-{iter_idx:03d}"
    if not base.exists():
        return
    bp_path = base / "blueprint.json"
    if not bp_path.exists():
        return

    tasks = await crud.get_all("tasks", "project_id = ?", (project_id,))
    task_dicts: list[dict] = []
    for t in tasks:
        deps_raw = t.get("deps") or "[]"
        os_raw = t.get("output_schema") or "{}"
        try:
            deps = json.loads(deps_raw) if isinstance(deps_raw, str) else (deps_raw or [])
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("patch_blueprint.deps_decode_failed",
                        task_id=t.get("id"), error=str(exc))
            deps = []
        try:
            os_obj = json.loads(os_raw) if isinstance(os_raw, str) else (os_raw or {})
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("patch_blueprint.schema_decode_failed",
                        task_id=t.get("id"), error=str(exc))
            os_obj = {}
        task_dicts.append({
            "id": t["id"],
            "title": t.get("title", ""),
            "detail": t.get("detail", ""),
            "kind": t.get("kind", "regular"),
            "agent_id": t.get("agent_id"),
            "deps": deps,
            "output_schema": os_obj,
        })

    try:
        existing = json.loads(bp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        log.warning("patch_blueprint.read_blueprint_failed",
                    path=str(bp_path), error=str(exc))
        existing = {}
    existing["tasks"] = task_dicts
    existing["project_id"] = project_id
    existing["project_name"] = project.get("name")
    bp_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def make_patch_blueprint_tool(session_id: str) -> PatchBlueprintTool:
    class _Bound(PatchBlueprintTool):
        _bound_session_id: ClassVar[str] = session_id

    return _Bound()


__all__ = ["PatchBlueprintTool", "make_patch_blueprint_tool"]
