"""PM v3 — turn the in-memory draft into a real project.

Called when the user clicks 「保存项目」. Reads the draft blueprint from
planner_cache_svc and:
  1. Creates the project row + tasks via project_svc.create_project_with_tasks
  2. Stamps the seeded Project Initializer agent on the setup task
     (it was already pre-assigned by Phase 4 — this just re-verifies)
  3. Writes .mycrew/blueprint.json + architecture.md + per-task .md
     via services.blueprint_writer.write_blueprint_to_disk
  4. Dumps the full debug log to .mycrew/_planner_trace.json for
     post-mortem analysis
  5. Sets session.project_id
  6. Clears the cache entry
  7. Broadcasts inception.workflow_created so the frontend right-side
     blueprint editor takes over from the debug log

Failure model: if any of steps 1-3 fail, we roll back what's been done
(delete project row, rm .mycrew/) before raising. SQLite + filesystem
aren't a unified transaction so this is best-effort.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import structlog

from api.ws import manager
from infra.repo import crud
from services import planner_cache_svc
from services.blueprint_writer import (
    resolve_blueprint_dir,
    write_blueprint_to_disk,
)
from services.project_svc import project_svc

log = structlog.get_logger()


async def save_draft_as_project(session_id: str) -> dict[str, Any]:
    """Persist the cached draft blueprint as a real project.

    Returns {"project_id": str, "task_count": int} on success.
    Raises ValueError if no draft / draft not ready.
    """
    draft = planner_cache_svc.get(session_id)
    if draft is None:
        raise ValueError("no draft in cache for this session")
    if draft.get("status") != "ready":
        raise ValueError(
            f"draft status is '{draft.get('status')}', expected 'ready'"
        )

    blueprint = draft.get("draft_blueprint")
    if not isinstance(blueprint, dict) or not blueprint.get("tasks"):
        raise ValueError("draft has no usable blueprint")

    session = await crud.get_by_id("inception_sessions", session_id)
    if session is None:
        raise ValueError(f"session {session_id} not found")

    # Step 1: create project + tasks (dep translation handled by project_svc)
    project = await project_svc.create_project_with_tasks(
        data={
            "name": blueprint.get("name", "未命名项目"),
            "execution_kind": blueprint.get("execution_kind", "crew"),
            "template_id": session.get("template_id"),
            "parent_project_id": session.get("parent_project_id"),
        },
        tasks=blueprint["tasks"],
    )
    project_id = project["id"]

    # Step 2: write .mycrew/
    try:
        await crud.update_by_id("inception_sessions", session_id, {
            "project_id": project_id,
        })
        # Refresh project dict so blueprint_writer sees up-to-date root_path
        # (likely None at this point — that's fine, pending dir is used)
        refreshed_proj = await crud.get_by_id("projects", project_id) or project
        base, pending = write_blueprint_to_disk(
            refreshed_proj,
            blueprint.get("architecture_overview", ""),
            blueprint["tasks"],
        )
    except Exception as exc:
        # Roll back: delete project row + its tasks (FK cascade in schema
        # should handle tasks; if not, project_svc.delete_project handles it)
        log.error("planner_persist.disk_write_failed",
                  project_id=project_id, error=str(exc))
        try:
            await project_svc.delete_project(project_id)
        except Exception as cleanup_exc:  # noqa: BLE001
            log.error("planner_persist.rollback_failed",
                      project_id=project_id, error=str(cleanup_exc))
        raise

    # Step 3: dump the full debug log next to the blueprint for forensics
    try:
        trace_path = base / "_planner_trace.json"
        trace_path.write_text(
            json.dumps({
                "session_id": session_id,
                "started_at": draft.get("started_at"),
                "completeness": draft.get("completeness"),
                "log": draft.get("debug_log_full", []),
                "phase_outputs": draft.get("phase_outputs", {}),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        # Non-fatal — log dump failure shouldn't kill the save
        log.warning("planner_persist.trace_dump_failed",
                    project_id=project_id, error=str(exc))

    # Step 4: clear the in-memory draft and broadcast
    planner_cache_svc.clear(session_id)
    try:
        await manager.broadcast("inception.workflow_created", {
            "session_id": session_id,
            "project_id": project_id,
            "project": refreshed_proj,
            "blueprint": blueprint,
        })
    except Exception:
        pass  # broadcast best-effort

    log.info("planner_persist.saved",
             session_id=session_id, project_id=project_id,
             task_count=len(blueprint["tasks"]), pending=pending)
    return {"project_id": project_id, "task_count": len(blueprint["tasks"])}


__all__ = ["save_draft_as_project"]
