"""Lifecycle routes — shutdown/recovery/state for Tauri integration (§14)."""
from fastapi import APIRouter
from fastapi.responses import FileResponse

from services.workflow_svc import workflow_svc
from services.mcp_svc import mcp_svc
from services.diagnostic_svc import export_diagnostic_bundle
from infra.llm.gateway import llm_gateway
from infra.repo import crud

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


async def _count_running_tasks(active_project_ids: list[str]) -> int:
    """Count tasks in 'running' state across all active projects."""
    if not active_project_ids:
        return 0
    placeholders = ",".join("?" for _ in active_project_ids)
    rows = await crud.get_all(
        "tasks",
        f"project_id IN ({placeholders}) AND status = 'running'",
        tuple(active_project_ids),
    )
    return len(rows)


@router.get("/state")
async def get_state():
    """Get current runtime state for shutdown decision tree.

    Tauri main process calls this before closing to check if
    there are running projects that need confirmation.
    """
    active = workflow_svc.get_active_projects()
    mcp_status = await mcp_svc.get_status_summary()
    running_tasks = await _count_running_tasks(active)

    return {
        "ok": True,
        "data": {
            "running_projects": len(active),
            "active_project_ids": active,
            "active_tasks": running_tasks,
            "mcp_count": mcp_status.get("online", 0),
        },
    }


@router.post("/pause-all")
async def pause_all():
    """Pause all running projects (shutdown step 1).

    Called by Tauri during graceful shutdown sequence.
    """
    count = await workflow_svc.pause_all()
    return {"ok": True, "data": {"paused_count": count}}


@router.post("/shutdown")
async def shutdown():
    """Full shutdown sequence (§14.1).

    1. Pause all projects
    2. Shutdown MCP pool
    3. Close LLM connections
    """
    paused = await workflow_svc.pause_all()
    await mcp_svc.shutdown_all()
    await llm_gateway.shutdown()

    return {
        "ok": True,
        "data": {
            "paused_projects": paused,
            "mcp_stopped": True,
            "llm_closed": True,
        },
    }


@router.post("/recover")
async def recover():
    """Recover projects that were running when app last closed (§14.2 STEP 5).

    Called on startup if last_state.json indicates interrupted projects.
    """
    recovered = await workflow_svc.recover()
    return {
        "ok": True,
        "data": {
            "recovered_projects": recovered,
            "count": len(recovered),
        },
    }


@router.post("/diagnostic-bundle")
async def diagnostic_bundle():
    """Export a diagnostic ZIP bundle (logs + redacted configs + system info).

    Plan §17.5 — for users to send when reporting bugs.
    """
    path = await export_diagnostic_bundle()
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
    )
