import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.workflow_svc import workflow_svc
from infra.repo import crud
from bootstrap.paths import OUTPUT_DIR

router = APIRouter(prefix="/workflow", tags=["workflow"])


class StartProjectBody(BaseModel):
    """Optional scaffold args. 2026-05-17: scaffold is no longer
    triggered through this route — start() rejects pending/failed
    projects with a "please use the path button" message. These
    fields stay in the schema for backward compatibility with old
    clients, but the server ignores them.
    """
    root_parent_path: str | None = None
    slug: str | None = None


@router.post("/projects/{project_id}/start")
async def start_project(project_id: str, body: StartProjectBody | None = None):
    body = body or StartProjectBody()
    try:
        await workflow_svc.start(
            project_id,
            root_parent_path=body.root_parent_path,
            slug=body.slug,
        )
        return {"ok": True, "data": {"project_id": project_id, "state": "running"}}
    except KeyError:
        raise HTTPException(404, detail="project not found")
    except ValueError as exc:
        return {"ok": False, "error": {"code": "validation_failed", "message": str(exc)}}


# ── PM v5+ scaffold endpoints (2026-05-17) ────────────────────────


class ScaffoldBody(BaseModel):
    """User-supplied parent directory + English slug. Together they
    determine where the Unity template gets cloned:
        <root_parent_path>/<slug>/
    """
    root_parent_path: str
    slug: str


@router.post("/projects/{project_id}/scaffold")
async def scaffold_project(project_id: str, body: ScaffoldBody):
    """Trigger an async git clone of the project's bound Unity template
    into <root_parent_path>/<slug>/. Returns 202 Accepted immediately;
    progress streamed via project.scaffold_* WS events. On success the
    project row's root_path is updated to the new child dir and
    scaffold_status flips to 'done'.

    Fires the ProjectCard 「路径」 button when the project is unsaved
    (scaffold_status='pending' or 'failed').
    """
    project = await crud.get_by_id("projects", project_id)
    if not project:
        raise HTTPException(404, detail="project not found")
    if project.get("scaffold_status") == "in_progress":
        return {"ok": False, "error": {
            "code": "in_progress",
            "message": "项目正在构建雏形，请等待完成",
        }}
    if project.get("scaffold_status") == "done":
        return {"ok": False, "error": {
            "code": "already_scaffolded",
            "message": "项目已构建过；想重新构建请用修复接口",
        }}
    # Fire-and-forget the clone; user gets immediate response
    asyncio.create_task(
        workflow_svc.scaffold_only(project_id, body.root_parent_path, body.slug),
    )
    return {"ok": True, "data": {"project_id": project_id, "status": "started"}}


@router.post("/projects/{project_id}/scaffold-repair")
async def repair_scaffold(project_id: str):
    """Re-run the clone with overwrite=True. Used after the structure
    audit reports missing critical files (e.g. user deleted
    ProjectSettings/ manually, git download truncated). Reads the
    project's stored root_parent_path + slug — no body needed.

    DESTRUCTIVE: wipes the existing child directory before re-cloning,
    so any user-side changes inside it are lost. Frontend must confirm
    with the user via the audit modal first.
    """
    project = await crud.get_by_id("projects", project_id)
    if not project:
        raise HTTPException(404, detail="project not found")
    if project.get("scaffold_status") == "in_progress":
        return {"ok": False, "error": {
            "code": "in_progress",
            "message": "项目正在构建雏形，请等待完成",
        }}
    parent = project.get("root_parent_path")
    root = project.get("root_path")
    # Derive slug from root_path (= <parent>/<slug>) since we don't
    # store it separately. Fallback to parsing if root_path missing.
    if not parent:
        return {"ok": False, "error": {
            "code": "missing_parent",
            "message": "项目缺少 root_parent_path，无法定位克隆目标。请从主页"
                       "项目卡片【路径】按钮重新选择目录",
        }}
    slug = Path(root).name if root else None
    if not slug:
        return {"ok": False, "error": {
            "code": "missing_slug",
            "message": "无法从 root_path 推导项目英文名",
        }}
    asyncio.create_task(
        workflow_svc.scaffold_only(project_id, parent, slug, overwrite=True),
    )
    return {"ok": True, "data": {
        "project_id": project_id,
        "status": "repairing",
        "target": f"{parent}/{slug}",
    }}


@router.get("/projects/{project_id}/scaffold-audit")
async def audit_scaffold(project_id: str):
    """Check that the project's scaffolded directory still contains the
    4 critical anchor paths (Assets/, Packages/manifest.json,
    ProjectSettings/ProjectVersion.txt, .mycrew_scaffolded). Returns
    the list of missing paths so the frontend can decide whether to
    pop the ScaffoldAuditModal before allowing 开始 to proceed.

    Returns 200 with ok=true and missing=[] for non-Unity projects
    (no scaffold needed) and for projects not yet scaffolded
    (audit_required is meaningless before clone).
    """
    project = await crud.get_by_id("projects", project_id)
    if not project:
        raise HTTPException(404, detail="project not found")
    status = project.get("scaffold_status")
    if status != "done":
        # Either non-Unity (null) or not yet scaffolded — nothing to
        # audit. UI shouldn't gate start on this.
        return {"ok": True, "data": {
            "applicable": False,
            "scaffold_status": status,
            "missing": [],
        }}
    root = project.get("root_path")
    if not root:
        return {"ok": True, "data": {
            "applicable": False,
            "scaffold_status": status,
            "missing": [],
        }}
    from services.template_cloner_svc import audit_against_skeleton
    missing = audit_against_skeleton(Path(root))
    return {"ok": True, "data": {
        "applicable": True,
        "scaffold_status": status,
        "root_path": root,
        "missing": missing,
    }}


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


@router.post("/projects/{project_id}/reset")
async def reset_project(
    project_id: str,
    delete_output_files: bool = Query(
        False,
        description=(
            "When true, also delete files at the project's root_path "
            "that any task declared in its output_paths. Use for "
            "debug-only projects where each fresh run must start with "
            "an empty workspace. Default false to protect user data."
        ),
    ),
):
    """Reset a project to its initial state — all tasks back to pending,
    project back to ready, MyCrew output artifacts wiped. Optionally
    also wipes the produced files at `root_path` (for debug projects).

    Drops the project from `_active` so the next start rebuilds the
    harness fresh.
    """
    try:
        result = await workflow_svc.reset_project(
            project_id, delete_output_files=delete_output_files,
        )
        return {"ok": True, "data": result}
    except KeyError:
        raise HTTPException(404, detail="project not found")


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
    except Exception as exc:
        # Surface state-machine / domain exceptions as 400 with a
        # human-readable error envelope so the frontend can show a
        # specific message rather than uvicorn's bare "Internal Server
        # Error" plain-text body (which apiFetch classifies as a
        # network failure → confusing "后端不可达" toast).
        from domain.harness.state_machine import InvalidTransition
        if isinstance(exc, InvalidTransition):
            return {
                "ok": False,
                "error": {"code": "invalid_state", "message": str(exc)},
            }
        raise


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


@router.get("/tasks/{task_id}/crew_progress")
async def get_task_crew_progress(task_id: str):
    """Reconstruct each Crew sub-step's status from on-disk artifacts.

    The task.sub_step WS event drives the live sub-card status, but the
    frontend's subStepStatus map is kept entirely in component state —
    a page refresh wipes it and you have to wait for the next sub_step
    event to repopulate. This endpoint lets CanvasCrewNode seed the
    map on mount by inspecting `output/<pid>/<tid>/sub/<i>_<role>_*`:

      - has _out.json → completed
      - has only _in.json
          • parent task.status in failed/validation_failed/stalled → failed
          • parent task.status in running → started (this is the live step)
          • else → pending (probably never ran — shouldn't normally happen)
      - no _in.json at all → pending
    """
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        raise HTTPException(404, detail="task not found")

    from bootstrap.paths import OUTPUT_DIR
    parent_status = task.get("status") or "pending"
    project_id = task.get("project_id") or ""
    sub_dir = OUTPUT_DIR / project_id / task_id / "sub"

    # Discover every step index that has at least one file on disk;
    # gather their role from the filename. We cap at 20 to avoid
    # surprises from a malformed directory.
    by_index: dict[int, dict[str, bool | str]] = {}
    if sub_dir.exists():
        for entry in sub_dir.iterdir():
            if not entry.is_file():
                continue
            # filename format: "<i>_<role>_<in|out>.<ext>"
            name = entry.name
            try:
                idx_str, rest = name.split("_", 1)
                idx = int(idx_str)
            except ValueError:
                continue
            if idx < 0 or idx > 20:
                continue
            role = rest.split("_", 1)[0] if "_" in rest else "?"
            slot = by_index.setdefault(idx, {"role": role, "has_in": False, "has_out": False})
            if name.endswith("_in.json"):
                slot["has_in"] = True
            elif name.endswith("_out.json"):
                slot["has_out"] = True

    failed_parent = parent_status in ("failed", "validation_failed", "stalled", "aborted")
    running_parent = parent_status == "running"

    steps = []
    for idx in sorted(by_index.keys()):
        slot = by_index[idx]
        role = slot["role"]
        # Synthetic contract step is fail-aware: read the json's
        # `passed` flag because the contract check has no _in.json
        # half-state — it's binary pass/fail.
        if role == "contract" and slot["has_out"]:
            out_path = sub_dir / f"{idx}_contract_out.json"
            try:
                payload = json.loads(out_path.read_text(encoding="utf-8"))
                passed = bool(payload.get("passed"))
                errors = payload.get("errors") or []
            except (OSError, json.JSONDecodeError, TypeError):
                passed = True
                errors = []
            steps.append({
                "step_index": idx,
                "role": "contract",
                "status": "completed" if passed else "failed",
                "errors": errors,
            })
            continue

        if slot["has_out"]:
            status = "completed"
        elif slot["has_in"]:
            if failed_parent:
                status = "failed"
            elif running_parent:
                status = "started"
            else:
                status = "pending"
        else:
            status = "pending"
        steps.append({
            "step_index": idx,
            "role": role,
            "status": status,
        })

    return {"ok": True, "data": {"task_id": task_id, "steps": steps}}


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
