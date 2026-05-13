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
