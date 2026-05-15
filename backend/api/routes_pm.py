"""PM v3 — endpoints exposing the in-memory draft cache to the frontend.

The 5-phase Crew itself is still driven by the existing
POST /inception/sessions/{id}/messages/stream (router → create_new sub
→ orchestrator) — this module only adds the cache management surface:

  GET  /pm/sessions/{sid}/state    — current draft + debug log replay
  POST /pm/sessions/{sid}/save     — turn draft into a real project
  POST /pm/sessions/{sid}/restart  — resume from the failed phase
  POST /pm/sessions/{sid}/cancel   — Stop button: hard-cancel + clear
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import planner_cache_svc
from services.planner_persist_svc import save_draft_as_project

router = APIRouter(prefix="/pm", tags=["pm"])


@router.get("/sessions/{session_id}/state")
async def get_pm_state(session_id: str):
    """Return everything the drawer needs to reconstruct the right
    panel after a navigation away / page refresh: status, current
    phase, full debug log, and the draft blueprint if ready."""
    state = planner_cache_svc.to_pm_state(session_id)
    return {"ok": True, "data": state}


@router.post("/sessions/{session_id}/save")
async def save_pm_draft(session_id: str):
    """User clicked 「保存项目」 — migrate the draft from cache into a
    real DB project + .mycrew/ files."""
    try:
        result = await save_draft_as_project(session_id)
    except ValueError as exc:
        return {"ok": False, "error": {"code": "no_draft", "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": {"code": "save_failed", "message": str(exc)}}
    return {"ok": True, "data": result}


class RestartBody(BaseModel):
    # Optional override; if absent, resume from the recorded failed_phase
    start_from: str | None = None


@router.post("/sessions/{session_id}/restart")
async def restart_pm(session_id: str, body: RestartBody | None = None):
    """User clicked 「从断点重来」 — re-run the crew starting at the
    failed phase. Upstream phase outputs are reused from the cache
    so we don't spend tokens redoing them.

    The actual kickoff happens in a fire-and-forget task here; the
    HTTP request returns immediately and progress flows via WS pm.log.
    Unlike the initial round, this endpoint does NOT block — caller
    polls pm_state or listens to events.
    """
    import asyncio
    from infra.repo import crud
    from agents.sub_agents._planner_orchestrator import run_crew

    draft = planner_cache_svc.get(session_id)
    if draft is None:
        raise HTTPException(404, detail="no draft for this session")

    start_from = (body.start_from if body else None) or draft.get("failed_phase")
    if not start_from:
        # Round was never failed — nothing to restart. Frontend
        # shouldn't hit this, but be polite.
        return {"ok": False, "error": {
            "code": "nothing_to_restart",
            "message": "草稿不在失败状态，无需重来。",
        }}

    session = await crud.get_by_id("inception_sessions", session_id)
    if session is None:
        raise HTTPException(404, detail="session not found")

    # Pull the original user message — for resumed phases that need
    # it as input (e.g. Phase 0/1 paths). Use the most recent user
    # message in the session.
    msgs = await crud.get_all(
        "inception_messages",
        "session_id = ? AND role = ?",
        (session_id, "user"),
    )
    last_user_msg = msgs[-1]["content"] if msgs else ""

    async def _resume_task() -> None:
        try:
            await run_crew(session, last_user_msg, start_from=start_from)
        except Exception:
            # Errors are already recorded into the cache by run_crew
            pass

    task = asyncio.create_task(_resume_task())
    planner_cache_svc.update(session_id, pm_task=task)
    return {"ok": True, "data": {"resumed_from": start_from}}


@router.post("/sessions/{session_id}/cancel")
async def cancel_pm(session_id: str):
    """User clicked Stop. Hard-cancels the asyncio.Task + marks cache
    as cancelled. The cache stays around so the user can see what
    completed before they aborted — they 新建对话 to clear it."""
    cancelled = planner_cache_svc.request_cancel(session_id)
    if not cancelled:
        return {"ok": False, "error": {
            "code": "no_run", "message": "没有正在跑的 PM 工作流。",
        }}
    return {"ok": True, "data": {"cancelled": True}}
