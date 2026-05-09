"""Lifecycle routes — shutdown/recovery/state for Tauri integration (§14)."""
from fastapi import APIRouter

from services.workflow_svc import workflow_svc
from services.mcp_svc import mcp_svc
from infra.llm.gateway import llm_gateway

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


@router.get("/state")
async def get_state():
    """Get current runtime state for shutdown decision tree.

    Tauri main process calls this before closing to check if
    there are running projects that need confirmation.
    """
    active = workflow_svc.get_active_projects()
    mcp_status = await mcp_svc.get_status_summary()

    return {
        "ok": True,
        "data": {
            "running_projects": len(active),
            "active_project_ids": active,
            "active_tasks": 0,  # TODO: count running tasks across projects
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
