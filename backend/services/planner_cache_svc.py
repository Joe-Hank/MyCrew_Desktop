"""PM v3 — in-memory draft cache.

Per the design decision in Q6, the entire 5-phase output stays in
backend RAM until the user clicks 「保存项目」. Survives drawer close
+ SPA navigation (because state lives in the backend, not the drawer).
Survives WS reconnect. Vanishes on backend process exit ("关程序").

One entry per inception session_id. Each entry tracks:
  - status: idle → running → ready | failed | cancelled
  - current_phase + cumulative debug_log (for the right-side log panel)
  - phase_outputs (intermediate Pydantic-validated payloads)
  - draft_blueprint (assembled after phase 5)
  - cancel_requested flag (Stop button sets this; orchestrator checks
    between phases and aborts gracefully)

Not a class — module-level dict + helpers, simplest possible. If the
process exits with a draft mid-flight, the user has to redo (matching
the user's stated semantics).
"""
from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()


_sessions: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


# ── Lifecycle ──────────────────────────────────────────────────────


def start_round(session_id: str) -> dict[str, Any]:
    """Initialise a fresh draft entry for a session. Returns the draft dict.

    If one already exists for this session, it's overwritten — caller is
    responsible for checking is_running() first if they need idempotency.
    """
    with _lock:
        draft = {
            "session_id": session_id,
            "status": "running",
            "current_phase": "completeness",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completeness": None,         # "ONELINE" / "PRD"
            "phase_outputs": {},          # phase name → Pydantic-validated dict
            "debug_log": [],              # broadcast log entries (preview-trimmed)
            "debug_log_full": [],         # full payloads, dumped to .mycrew on save
            "draft_blueprint": None,
            "cancel_requested": False,
            "error": None,
            "failed_phase": None,
            "pm_task": None,              # asyncio.Task running the crew
        }
        _sessions[session_id] = draft
        return draft


def get(session_id: str) -> dict[str, Any] | None:
    with _lock:
        return _sessions.get(session_id)


def is_running(session_id: str) -> bool:
    with _lock:
        d = _sessions.get(session_id)
        return d is not None and d.get("status") == "running"


def update(session_id: str, **fields: Any) -> None:
    with _lock:
        d = _sessions.get(session_id)
        if d is None:
            return
        d.update(fields)


def set_phase_output(session_id: str, phase: str, payload: Any) -> None:
    with _lock:
        d = _sessions.get(session_id)
        if d is None:
            return
        d["phase_outputs"][phase] = payload


def get_phase_output(session_id: str, phase: str) -> Any:
    with _lock:
        d = _sessions.get(session_id)
        if d is None:
            return None
        return d["phase_outputs"].get(phase)


def append_log(session_id: str, entry: dict[str, Any]) -> None:
    """Append a debug log entry. Stores both the trimmed (broadcast) and
    full versions so the broadcast stays light but the eventual
    _planner_trace.json dump can carry full payloads."""
    full_entry = dict(entry)
    trimmed = dict(entry)
    if "payload_preview" in trimmed:
        s = str(trimmed["payload_preview"])
        if len(s) > 1024:
            trimmed["payload_preview"] = s[:1024] + "…(trimmed)"
    with _lock:
        d = _sessions.get(session_id)
        if d is None:
            return
        d["debug_log"].append(trimmed)
        d["debug_log_full"].append(full_entry)


def clear(session_id: str) -> None:
    """Drop the session's draft. Called on:
      - 用户点保存（migrated to DB+disk, no longer needed here）
      - 用户点新建对话（abandons the draft）
      - 整轮失败 + 用户确认放弃
    """
    with _lock:
        _sessions.pop(session_id, None)


def request_cancel(session_id: str) -> bool:
    """Mark cancel requested. Orchestrator checks this between phases
    and returns early. Also cancels the asyncio.Task immediately to
    abort any in-flight LLM call. Returns True if a draft was found."""
    with _lock:
        d = _sessions.get(session_id)
        if d is None:
            return False
        d["cancel_requested"] = True
        d["status"] = "cancelled"
        task: asyncio.Task | None = d.get("pm_task")
    # Cancel outside the lock to avoid deadlocking with the task's
    # finally-clause if it touches the cache.
    if task is not None and not task.done():
        task.cancel()
    log.info("planner_cache.cancel_requested", session_id=session_id)
    return True


# ── pm_state endpoint helper ────────────────────────────────────────


def to_pm_state(session_id: str) -> dict[str, Any]:
    """Serialise the draft for the GET /pm_state endpoint.

    Returns a dict safe to send over JSON — strips internal fields like
    the asyncio.Task reference. Always returns *something*, even for
    sessions that have never started a PM round (status='idle')."""
    d = get(session_id)
    if d is None:
        return {
            "session_id": session_id,
            "status": "idle",
            "current_phase": None,
            "debug_log": [],
            "draft_blueprint": None,
            "completeness": None,
            "error": None,
            "failed_phase": None,
        }
    return {
        "session_id": session_id,
        "status": d["status"],
        "current_phase": d["current_phase"],
        "started_at": d.get("started_at"),
        "debug_log": list(d["debug_log"]),
        "draft_blueprint": d.get("draft_blueprint"),
        "completeness": d.get("completeness"),
        "error": d.get("error"),
        "failed_phase": d.get("failed_phase"),
    }


__all__ = [
    "start_round",
    "get",
    "is_running",
    "update",
    "set_phase_output",
    "get_phase_output",
    "append_log",
    "clear",
    "request_cancel",
    "to_pm_state",
]
