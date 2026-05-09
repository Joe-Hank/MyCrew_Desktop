import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.workflow_svc import workflow_svc
from infra.repo import crud
from bootstrap.paths import OUTPUT_DIR

router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.post("/projects/{project_id}/start")
async def start_project(project_id: str):
    try:
        await workflow_svc.start(project_id)
        return {"ok": True, "data": {"project_id": project_id, "state": "running"}}
    except KeyError:
        raise HTTPException(404, detail="project not found")
    except ValueError as exc:
        return {"ok": False, "error": {"code": "validation_failed", "message": str(exc)}}


@router.post("/projects/{project_id}/pause")
async def pause_project(project_id: str):
    try:
        await workflow_svc.pause(project_id)
        return {"ok": True, "data": {"project_id": project_id, "state": "paused"}}
    except KeyError:
        raise HTTPException(404, detail="project not active")


@router.post("/projects/{project_id}/resume")
async def resume_project(project_id: str):
    try:
        await workflow_svc.resume(project_id)
        return {"ok": True, "data": {"project_id": project_id, "state": "running"}}
    except KeyError:
        raise HTTPException(404, detail="project not active")


@router.post("/projects/{project_id}/abort")
async def abort_project(project_id: str, reason: str = ""):
    try:
        await workflow_svc.abort(project_id, reason)
        return {"ok": True, "data": {"project_id": project_id, "state": "aborted"}}
    except KeyError:
        raise HTTPException(404, detail="project not active")


@router.post("/projects/{project_id}/tasks/{task_id}/retry")
async def retry_task(project_id: str, task_id: str):
    try:
        await workflow_svc.retry_task(project_id, task_id)
        return {"ok": True, "data": {"task_id": task_id, "state": "running"}}
    except KeyError:
        raise HTTPException(404, detail="project or task not found")


@router.get("/active")
async def active_projects():
    return {"ok": True, "data": {"projects": workflow_svc.get_active_projects()}}


@router.get("/tasks/{task_id}/io")
async def get_task_io(task_id: str, direction: str = Query("out", pattern="^(in|out)$")):
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        raise HTTPException(404, detail="task not found")

    ref_field = "io_out_ref" if direction == "out" else "io_in_ref"
    ref_path = task.get(ref_field)
    if not ref_path:
        return {"ok": True, "data": {"direction": direction, "structured": None, "raw": None}}

    from pathlib import Path
    p = Path(ref_path)
    structured = None
    raw = None

    if direction == "out":
        if p.exists():
            try:
                structured = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        raw_path = p.parent / "out.md"
        if raw_path.exists():
            try:
                raw = raw_path.read_text(encoding="utf-8")
            except OSError:
                pass
    else:
        if p.exists():
            try:
                structured = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    return {"ok": True, "data": {"direction": direction, "structured": structured, "raw": raw}}


class TaskUpdate(BaseModel):
    title: str | None = None
    detail: str | None = None
    agent_id: str | None = None


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskUpdate):
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        raise HTTPException(404, detail="task not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        return {"ok": True, "data": dict(task)}
    await crud.update_by_id("tasks", task_id, updates)
    updated = await crud.get_by_id("tasks", task_id)
    return {"ok": True, "data": dict(updated)}
