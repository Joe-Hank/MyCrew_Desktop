"""Cross-thread capture of `emit_output` tool results.

CrewAI's `kickoff` runs in a worker thread; the `emit_output` tool stores
the validated payload here so `workflow_svc` can read it after kickoff
completes — bypassing the fragile "extract JSON from text" heuristic.

Keyed by task_id; expected to be `set_output` exactly once per task run
and `pop_output` exactly once by the workflow service.
"""
from __future__ import annotations

import threading
from typing import Any

_outputs: dict[str, Any] = {}
_lock = threading.Lock()


def set_output(task_id: str, payload: Any) -> None:
    with _lock:
        _outputs[task_id] = payload


def pop_output(task_id: str) -> Any:
    with _lock:
        return _outputs.pop(task_id, None)


def has_output(task_id: str) -> bool:
    with _lock:
        return task_id in _outputs


# ── PM v3 planner per-phase capture ─────────────────────────────────
# Keyed by (session_id, phase) so each phase's submit_xxx tool can stash
# its validated payload for the orchestrator to pop between phases.

_planner_outputs: dict[tuple[str, str], Any] = {}


def set_planner_output(session_id: str, phase: str, payload: Any) -> None:
    with _lock:
        _planner_outputs[(session_id, phase)] = payload


def pop_planner_output(session_id: str, phase: str) -> Any:
    with _lock:
        return _planner_outputs.pop((session_id, phase), None)


def clear_planner_session(session_id: str) -> None:
    """Drop every per-phase capture for a session — used when a PM round
    finishes (success or cancel) so stale payloads can't leak into a
    later round."""
    with _lock:
        keys = [k for k in _planner_outputs if k[0] == session_id]
        for k in keys:
            _planner_outputs.pop(k, None)
