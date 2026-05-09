import asyncio
import os
import signal

import structlog
from fastapi import APIRouter

log = structlog.get_logger()

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"ok": True, "data": {"status": "healthy", "version": "0.1.0"}}


@router.get("/lifecycle/state")
async def lifecycle_state():
    from services.workflow_svc import workflow_svc
    from services.mcp_svc import mcp_svc

    active = workflow_svc.get_active_projects()
    status = await mcp_svc.get_status_summary()
    return {
        "ok": True,
        "data": {
            "running_projects": len(active),
            "active_tasks": 0,
            "mcp_online": status.get("online", 0),
            "mcp_total": status.get("total", 0),
        },
    }


@router.post("/lifecycle/shutdown")
async def lifecycle_shutdown():
    log.info("lifecycle.shutdown_requested")

    async def _do_shutdown():
        await asyncio.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    asyncio.create_task(_do_shutdown())
    return {"ok": True, "data": {"message": "shutting down"}}


@router.post("/lifecycle/pause-all")
async def lifecycle_pause_all():
    from services.workflow_svc import workflow_svc

    count = await workflow_svc.pause_all()
    return {"ok": True, "data": {"paused": count}}
