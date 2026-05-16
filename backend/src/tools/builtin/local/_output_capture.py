"""Cross-thread capture of `emit_output` tool results.

CrewAI's `kickoff` runs in a worker thread; the `emit_output` tool stores
the validated payload here so `workflow_svc` can read it after kickoff
completes — bypassing the fragile "extract JSON from text" heuristic.

Keyed by task_id; expected to be `set_output` exactly once per task run
and `pop_output` exactly once by the workflow service.

TTL note (audit 2026-05-16 Phase 2): every set_* writes an insertion
timestamp; `_evict_expired` removes entries older than the per-bucket
TTL on every read. This guards against leaks when a task crashes before
`pop_output` runs, or a PM round dies before `clear_planner_session`.
"""
from __future__ import annotations

import threading
import time
from typing import Any

# Task-level capture TTL: 1 hour. The intended lifetime is "between
# kickoff and the workflow_svc post-process", which is seconds in the
# happy path; an hour is generous enough that a stuck Crew step still
# pops cleanly while preventing crashed tasks from accumulating
# indefinitely.
_TASK_OUTPUT_TTL_S = 60 * 60

# Planner-output TTL: 4 hours. PM rounds normally finish in minutes;
# longer drafts (user walking away mid-grill) get cleared without
# permanently consuming RAM.
_PLANNER_OUTPUT_TTL_S = 4 * 60 * 60

# (payload, inserted_at_monotonic) keyed by task_id / (session_id, phase).
_outputs: dict[str, tuple[Any, float]] = {}
_planner_outputs: dict[tuple[str, str], tuple[Any, float]] = {}
_lock = threading.Lock()


def _evict_expired(now: float | None = None) -> None:
    """Remove entries past their TTL. Called from every public op so
    eviction is amortised — no separate janitor task needed."""
    now = now if now is not None else time.monotonic()
    for k, (_, ts) in list(_outputs.items()):
        if now - ts > _TASK_OUTPUT_TTL_S:
            _outputs.pop(k, None)
    for k, (_, ts) in list(_planner_outputs.items()):
        if now - ts > _PLANNER_OUTPUT_TTL_S:
            _planner_outputs.pop(k, None)


def set_output(task_id: str, payload: Any) -> None:
    with _lock:
        _evict_expired()
        _outputs[task_id] = (payload, time.monotonic())


def pop_output(task_id: str) -> Any:
    with _lock:
        _evict_expired()
        entry = _outputs.pop(task_id, None)
        return entry[0] if entry is not None else None


def has_output(task_id: str) -> bool:
    with _lock:
        _evict_expired()
        return task_id in _outputs


# ── PM v3 planner per-phase capture ─────────────────────────────────
# Keyed by (session_id, phase) so each phase's submit_xxx tool can stash
# its validated payload for the orchestrator to pop between phases.

def set_planner_output(session_id: str, phase: str, payload: Any) -> None:
    with _lock:
        _evict_expired()
        _planner_outputs[(session_id, phase)] = (payload, time.monotonic())


def pop_planner_output(session_id: str, phase: str) -> Any:
    with _lock:
        _evict_expired()
        entry = _planner_outputs.pop((session_id, phase), None)
        return entry[0] if entry is not None else None


def clear_planner_session(session_id: str) -> None:
    """Drop every per-phase capture for a session — used when a PM round
    finishes (success or cancel) so stale payloads can't leak into a
    later round."""
    with _lock:
        keys = [k for k in _planner_outputs if k[0] == session_id]
        for k in keys:
            _planner_outputs.pop(k, None)
