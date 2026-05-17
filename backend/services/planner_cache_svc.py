"""PM v3 — draft cache with disk persistence (2026-05-17 update).

Originally pure in-memory (`关程序 → 蒸发`). With uvicorn --reload
killing the backend any time we edit a source file in api/services/
domain/ports/infra/bootstrap, a 15-minute PM run was guaranteed to
get yanked partway, and the cache loss meant the user couldn't even
see WHERE it stopped — the UI just went blank.

New behaviour:
  - Every mutator (start_round / update / set_phase_output / append_log)
    schedules a debounced async write to `data/runtime/planner_cache.json`
    via _schedule_persist() (200ms coalescing).
  - load_persisted_sessions() runs in app startup. Any session whose
    persisted status was 'running' gets flipped to 'interrupted' so the
    frontend can render a 「从断点重来」 affordance against it.
  - The asyncio.Task reference is NEVER persisted (it doesn't survive
    process exit anyway).

The on-disk format is the same dict shape, except `pm_task` is dropped
and timestamps stay ISO. Bad/truncated JSON on load is treated as no
cache (we don't crash startup).

Other than persistence, the API surface is unchanged — module-level
dict + helpers, same callers.
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


_sessions: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

# ── Persistence wiring ────────────────────────────────────────────
#
# We persist to RUNTIME_DIR/planner_cache.json. The write is debounced
# (200ms) so a phase that does 5 quick set_phase_output / update calls
# only triggers one disk flush. Import the path lazily so this module
# doesn't pull `bootstrap.paths` at import time (which can deadlock if
# something downstream pulls planner_cache_svc during paths setup).

_PERSIST_DELAY = 0.2  # seconds — Coalesce bursts of writes
_persist_task: asyncio.Task | None = None
_persist_loop: asyncio.AbstractEventLoop | None = None
_persist_dirty = False


def _persist_path() -> Path:
    from bootstrap.paths import RUNTIME_DIR
    return RUNTIME_DIR / "planner_cache.json"


def _serialise_sessions() -> dict[str, Any]:
    """Take a snapshot safe for JSON dump. The pm_task asyncio.Task
    reference can't be pickled and doesn't survive restart anyway."""
    with _lock:
        out: dict[str, Any] = {}
        for sid, draft in _sessions.items():
            slim = {k: v for k, v in draft.items() if k != "pm_task"}
            out[sid] = slim
        return out


def _write_to_disk() -> None:
    """Synchronous write — called from within the debounced task. Safe
    to fail silently (best-effort; the next mutation will retry)."""
    try:
        snapshot = _serialise_sessions()
        path = _persist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=None, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("planner_cache.persist_failed", error=str(exc))


async def _debounced_flush() -> None:
    """Coalesce a burst of mutations into one disk write."""
    global _persist_dirty
    try:
        await asyncio.sleep(_PERSIST_DELAY)
        if _persist_dirty:
            _persist_dirty = False
            _write_to_disk()
    except asyncio.CancelledError:
        pass


def _schedule_persist() -> None:
    """Called by every mutator. Sets the dirty flag and ensures a
    debounced flush task is queued on the event loop. Idempotent — if a
    flush is already pending we just leave the flag for it to pick up."""
    global _persist_task, _persist_loop, _persist_dirty
    _persist_dirty = True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called outside an event loop (e.g. unit tests / sync helper).
        # Just write immediately + return.
        _write_to_disk()
        return
    _persist_loop = loop
    if _persist_task is None or _persist_task.done():
        _persist_task = loop.create_task(_debounced_flush())


def load_persisted_sessions() -> int:
    """App-startup hook. Reads the JSON cache and seeds `_sessions`.
    Any draft whose persisted status was 'running' or 'idle'-with-
    in-flight-phase gets flipped to 'interrupted' so the UI can show
    a resume affordance. Returns the number of sessions restored.
    """
    path = _persist_path()
    if not path.exists():
        return 0
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return 0
    except Exception as exc:  # noqa: BLE001
        log.warning("planner_cache.load_failed", error=str(exc))
        return 0

    restored = 0
    with _lock:
        for sid, draft in data.items():
            if not isinstance(draft, dict):
                continue
            # Sessions that were mid-flight when we died → mark
            # 'interrupted' (a new status the frontend treats as
            # resume-from-breakpoint candidate). Don't carry pm_task.
            if draft.get("status") == "running":
                draft["status"] = "interrupted"
                draft["error"] = (
                    draft.get("error")
                    or "进程意外终止（可能是 dev 模式下的代码热重载）— "
                       "点【从断点重来】恢复 PM 工作流。"
                )
            draft.pop("pm_task", None)
            _sessions[sid] = draft
            restored += 1
    log.info("planner_cache.loaded", count=restored, path=str(path))
    return restored


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
    _schedule_persist()
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
    _schedule_persist()


def set_phase_output(session_id: str, phase: str, payload: Any) -> None:
    with _lock:
        d = _sessions.get(session_id)
        if d is None:
            return
        d["phase_outputs"][phase] = payload
    _schedule_persist()


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
    _schedule_persist()


def clear(session_id: str) -> None:
    """Drop the session's draft. Called on:
      - 用户点保存（migrated to DB+disk, no longer needed here）
      - 用户点新建对话（abandons the draft）
      - 整轮失败 + 用户确认放弃
    """
    with _lock:
        _sessions.pop(session_id, None)
    _schedule_persist()


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
        # PM v3.1 (2026-05-17): on restart, sessions whose last
        # persisted status was 'running' get flipped to 'interrupted'
        # so the UI can offer a 「从断点重来」 button. last_completed
        # tells the user how far PM got before the crash.
        "last_completed_phase": _last_completed_phase(d),
    }


def _last_completed_phase(d: dict[str, Any]) -> str | None:
    """Return the last phase that has a captured payload — the natural
    resume point if the user wants to continue from breakpoint."""
    outputs = d.get("phase_outputs") or {}
    # Phase order matches PHASES in _planner_orchestrator
    for phase in (
        "agent_assignment", "code_contract", "project_mgmt",
        "review", "system_design", "concept", "completeness",
    ):
        if phase in outputs:
            return phase
    return None


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
    "load_persisted_sessions",
]
