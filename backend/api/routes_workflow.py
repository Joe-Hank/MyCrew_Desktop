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
async def retry_task(
    project_id: str,
    task_id: str,
    cleanup_artifacts: bool = Query(True),
):
    """Re-run a failed task.

    `cleanup_artifacts=true` (default) wipes the task's previous outputs
    (sub/ dir + out.json/md) before the rerun. The frontend's confirm
    dialog drives this flag from the user's choice; setting it false
    preserves residue for the cases where the user knows the prior run
    only failed downstream of emit_output.
    """
    try:
        await workflow_svc.retry_task(
            project_id, task_id, cleanup_artifacts=cleanup_artifacts,
        )
        return {"ok": True, "data": {"task_id": task_id, "state": "running"}}
    except KeyError:
        raise HTTPException(404, detail="project or task not found")


@router.get("/active")
async def active_projects():
    return {"ok": True, "data": {"projects": workflow_svc.get_active_projects()}}


@router.get("/projects/{project_id}/required-mcps")
async def project_required_mcps(project_id: str):
    """List MCP servers this project's tasks actually need + their
    current connection status. Used by:
      - TaskHeader's right-side status row (one chip per server)
      - The Start button's pre-flight gate (refuse start if any
        required server is not connected)
    """
    try:
        servers = await workflow_svc.required_mcps(project_id)
    except KeyError:
        raise HTTPException(404, detail="project not found")
    return {"ok": True, "data": {"servers": servers}}


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


@router.get("/tasks/{task_id}/failure_analysis")
async def get_task_failure_analysis(task_id: str):
    """Read the LLM-precomputed failure diagnosis for this task.

    The failure_analyzer module writes this field the moment a task
    transitions to failed / validation_failed. Returns:

      - status: "ready"  + text + at  → diagnosis is available
      - status: "pending"             → task is failure-y but the LLM
                                        hasn't finished yet; frontend
                                        shows a spinner until
                                        task.failure_analyzed WS event
      - status: "not_failed"          → task isn't in a failure state,
                                        button shouldn't have rendered
    """
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        raise HTTPException(404, detail="task not found")
    status = task.get("status")
    is_failurey = status in ("failed", "validation_failed", "stalled", "blocked")
    text = task.get("failure_analysis")
    if not is_failurey:
        return {"ok": True, "data": {
            "status": "not_failed",
            "text": None,
            "at": None,
        }}
    if not text:
        return {"ok": True, "data": {
            "status": "pending",
            "text": None,
            "at": None,
            "validation_errors": task.get("validation_errors"),
            "last_error": task.get("last_error"),
        }}
    return {"ok": True, "data": {
        "status": "ready",
        "text": text,
        "at": task.get("failure_analysis_at"),
        "validation_errors": task.get("validation_errors"),
        "last_error": task.get("last_error"),
    }}


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
            "step_index": step_index,
            "in": None, "out": None,
            "raw_in": None, "raw_out": None,
            # `raw` is kept as an alias of raw_out for any pre-2026-05-17
            # frontend builds that still read it; current frontend uses
            # raw_in / raw_out per tab.
            "raw": None,
        }}

    def _find_one(suffix: str) -> Path | None:
        # Files are named "<i>_<role>_<in|out>.<ext>"; role is unknown
        # client-side so glob for the prefix + suffix.
        for candidate in sub_dir.glob(f"{step_index}_*_{suffix}"):
            return candidate
        return None

    def _read_text(p: Path | None) -> str | None:
        if not p or not p.exists():
            return None
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return None

    def _read_json(p: Path | None) -> dict | None:
        s = _read_text(p)
        if s is None:
            return None
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return None

    in_struct = _read_json(_find_one("in.json"))
    out_struct = _read_json(_find_one("out.json"))
    raw_in = _read_text(_find_one("in.md"))
    raw_out = _read_text(_find_one("out.md"))

    return {"ok": True, "data": {
        "step_index": step_index,
        "in": in_struct, "out": out_struct,
        "raw_in": raw_in, "raw_out": raw_out,
        # Back-compat alias for older frontend builds.
        "raw": raw_out,
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
    # PM v4: which performer kind (agent / crew) is bound, and the id
    # of that performer. The frontend's TaskEditModal sets all three of
    # {agent_id, performer_kind, performer_id} when the user picks a
    # crew (agent_id cleared to null, kind/id set) so workflow_svc
    # routes through _run_crew instead of _run_agent.
    performer_kind: str | None = None
    performer_id: str | None = None
    # Canvas-editable fields: dependency list (upstream task ids) and node
    # position. All optional; the partial-PUT semantics (only fields the
    # client actually sends get applied) come from `exclude_unset=True`
    # below — so a drag handler sending {position_x, position_y} won't
    # accidentally clobber agent_id with null.
    deps: list[str] | None = None
    position_x: float | None = None
    position_y: float | None = None


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, body: TaskUpdate):
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        raise HTTPException(404, detail="task not found")
    updates: dict = {}
    # exclude_unset honours partial PUTs: only fields the client put in
    # the JSON body get touched. Without this, omitted nullable fields
    # would silently be wiped to NULL on every drag-position save.
    # `null` explicitly sent by the client still comes through and
    # clears the column — needed when the user picks "(待指定)" in the
    # performer dropdown.
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "deps":
            updates[k] = json.dumps(v) if v is not None else None
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
