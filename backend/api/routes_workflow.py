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


class TaskGuidanceChatBody(BaseModel):
    message: str
    # PM v4 sub-card chat: when set, the guidance helper scopes its
    # context to a single Crew step (reads sub/<i>_*_in/out.json instead
    # of the parent task's in.md/out.md). Omit for the legacy
    # task-level chat.
    step_index: int | None = None
    agent_id: str | None = None


@router.post("/tasks/{task_id}/guidance")
async def task_guidance_chat(task_id: str, body: TaskGuidanceChatBody):
    """Single-turn LLM guidance about why a task didn't complete.

    Stateless: each call is independent — the frontend keeps its own
    scrollback. The agent is strictly read-only (won't retry, won't
    edit the task) and refuses requests that ask it to do so.

    `step_index` scopes the helper to a single Crew step's IO when set.
    """
    from agents.task_guidance import chat as guidance_chat
    result = await guidance_chat(
        task_id, body.message,
        step_index=body.step_index, step_agent_id=body.agent_id,
    )
    if result.get("ok"):
        return {"ok": True, "data": {"reply": result["reply"]}}
    return {"ok": False, "error": {"code": result.get("error", "unknown"),
                                    "message": result.get("reply", "")}}


@router.get("/tasks/{task_id}/sub_io")
async def get_task_sub_io(task_id: str, step_index: int = Query(..., ge=0)):
    """PM v4: read a single Crew sub-step's structured + markdown IO.

    Returns the in/out JSON for the requested step plus its human-readable
    .md companion (the head/exec/qa step writer produces both)."""
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        raise HTTPException(404, detail="task not found")

    from bootstrap.paths import OUTPUT_DIR
    from pathlib import Path
    project_id = task.get("project_id")
    sub_dir = OUTPUT_DIR / (project_id or "") / task_id / "sub"
    if not sub_dir.exists():
        return {"ok": True, "data": {
            "step_index": step_index, "in": None, "out": None, "raw": None,
        }}

    def _find_one(suffix: str) -> Path | None:
        # Files are named "<i>_<role>_<in|out>.<ext>"; role is unknown
        # client-side so glob for the prefix + suffix.
        for candidate in sub_dir.glob(f"{step_index}_*_{suffix}"):
            return candidate
        return None

    in_struct = None
    out_struct = None
    raw_md = None

    in_json = _find_one("in.json")
    if in_json and in_json.exists():
        try:
            in_struct = json.loads(in_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    out_json = _find_one("out.json")
    if out_json and out_json.exists():
        try:
            out_struct = json.loads(out_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    out_md = _find_one("out.md")
    if out_md and out_md.exists():
        try:
            raw_md = out_md.read_text(encoding="utf-8")
        except OSError:
            pass

    return {"ok": True, "data": {
        "step_index": step_index,
        "in": in_struct, "out": out_struct, "raw": raw_md,
    }}


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
        # Pair with in.md (human-readable view) when available — same
        # pattern as out.md for the output side.
        raw_path = p.parent / "in.md"
        if raw_path.exists():
            try:
                raw = raw_path.read_text(encoding="utf-8")
            except OSError:
                pass

    return {"ok": True, "data": {"direction": direction, "structured": structured, "raw": raw}}


class TaskUpdate(BaseModel):
    title: str | None = None
    detail: str | None = None
    agent_id: str | None = None
    # Canvas-editable fields: dependency list (upstream task ids) and node
    # position. All optional; only non-None fields are persisted, so a partial
    # PUT from the drag handler can send just {position_x, position_y}.
    deps: list[str] | None = None
    position_x: float | None = None
    position_y: float | None = None


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskUpdate):
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        raise HTTPException(404, detail="task not found")
    updates: dict = {}
    for k, v in body.model_dump().items():
        if v is None:
            continue
        # `deps` lives in DB as a JSON string. Serialise here so the route's
        # JSON-list API surface matches what the rest of the codebase reads.
        if k == "deps":
            updates[k] = json.dumps(v)
        else:
            updates[k] = v
    if not updates:
        return {"ok": True, "data": dict(task)}
    await crud.update_by_id("tasks", task_id, updates)
    updated = await crud.get_by_id("tasks", task_id)
    return {"ok": True, "data": dict(updated)}


class TaskCreate(BaseModel):
    project_id: str
    title: str = "新任务"
    detail: str = ""
    agent_id: str | None = None
    deps: list[str] = []
    kind: str = "regular"
    position_x: float | None = None
    position_y: float | None = None


@router.post("/tasks")
async def create_task(body: TaskCreate):
    # Verify project exists so we don't strand a task under a deleted id.
    project = await crud.get_by_id("projects", body.project_id)
    if not project:
        raise HTTPException(404, detail="project not found")
    row = await crud.insert("tasks", {
        "project_id": body.project_id,
        "title": body.title,
        "detail": body.detail,
        "agent_id": body.agent_id,
        "kind": body.kind,
        "output_schema": "{}",
        "status": "pending",
        "deps": json.dumps(body.deps),
        "position_x": body.position_x,
        "position_y": body.position_y,
    }, id_prefix="task_")
    return {"ok": True, "data": dict(row)}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        raise HTTPException(404, detail="task not found")
    project_id = task["project_id"]
    # Cascade: remove this task id from every sibling task's deps array so
    # the canvas doesn't dangle edges to a deleted node.
    siblings = await crud.get_all("tasks", "project_id = ?", (project_id,))
    for sib in siblings:
        if sib["id"] == task_id:
            continue
        raw = sib.get("deps", "[]")
        try:
            dep_ids = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            dep_ids = []
        if task_id in dep_ids:
            new_deps = [d for d in dep_ids if d != task_id]
            await crud.update_by_id("tasks", sib["id"], {
                "deps": json.dumps(new_deps),
            })
    await crud.delete_by_id("tasks", task_id)
    return {"ok": True, "data": {"id": task_id, "project_id": project_id}}
