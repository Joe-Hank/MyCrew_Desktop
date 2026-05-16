"""Regression test for the 2026-05-16 美术资产组 false-positive
"file_paths is required" validation failure.

The Crew walker's run_crew_step_with_crewai used to pop_output() at
end of every step, including QA. Since QA's emit_output is bound to
the parent task_id, the pop consumed the parent's captured payload —
workflow_svc's later pop_output(parent_task_id) returned None, fell
back to JSON-text extraction on the Chinese summary text, produced
extracted={}, then failed schema validation. The user saw
"file_paths required" even though QA had emitted a valid payload
with file_paths in it.

Fix: peek instead of pop when step_task_key == parent_task_id, so
the payload survives until workflow_svc owns the final removal.
"""
from __future__ import annotations

import pytest

from src.tools.builtin.local._output_capture import (
    set_output, pop_output, peek_output,
)


def test_peek_returns_value_without_consuming():
    set_output("task_xyz", {"file_paths": ["a.png", "b.png"]})

    # Two consecutive peeks both return the value (no consumption).
    assert peek_output("task_xyz") == {"file_paths": ["a.png", "b.png"]}
    assert peek_output("task_xyz") == {"file_paths": ["a.png", "b.png"]}

    # pop after peek still works.
    assert pop_output("task_xyz") == {"file_paths": ["a.png", "b.png"]}
    assert pop_output("task_xyz") is None


def test_peek_missing_returns_none():
    assert peek_output("task_never_set") is None


def test_peek_after_pop_returns_none():
    set_output("task_lifecycle", {"v": 1})
    pop_output("task_lifecycle")
    assert peek_output("task_lifecycle") is None
