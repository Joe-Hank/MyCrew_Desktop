"""Tests for the Debugger fast-path skip (Option B).

When final_qa reports verdict='pass' the Debugger task has nothing to
do; workflow_svc._maybe_skip_debugger short-circuits so we don't burn
LLM tokens. When final_qa reports warn/fail the Debugger should
actually run.
"""
from __future__ import annotations

import pytest

from domain.harness.task_runner import TaskInput
from services.workflow_svc import WorkflowService


def _input(kind: str, upstream: dict) -> TaskInput:
    return TaskInput(
        task_id="dbg_task",
        title="auto fix",
        detail="",
        agent_id="agent_dbg",
        output_schema={},
        upstream_outputs=upstream,
        kind=kind,
    )


class _StubCrud:
    """Single-row stub: any get_by_id returns the dict it was given."""
    def __init__(self, rows: dict) -> None:
        self._rows = rows

    async def get_by_id(self, table, row_id):
        return self._rows.get(row_id)


@pytest.mark.asyncio
async def test_skips_when_final_qa_passed(monkeypatch):
    monkeypatch.setattr(
        "services.workflow_svc.crud",
        _StubCrud({"qa_task": {"id": "qa_task", "kind": "final_qa"}}),
    )
    svc = WorkflowService()
    task_input = _input(
        "debugger",
        {"qa_task": {"verdict": "pass", "issues": []}},
    )
    fast = await svc._maybe_skip_debugger(task_input)
    assert fast is not None
    assert fast["verdict"] == "fixed"
    assert fast["fixes_applied"] == []
    assert fast["issues_escalated"] == []


@pytest.mark.asyncio
async def test_runs_when_final_qa_failed(monkeypatch):
    monkeypatch.setattr(
        "services.workflow_svc.crud",
        _StubCrud({"qa_task": {"id": "qa_task", "kind": "final_qa"}}),
    )
    svc = WorkflowService()
    task_input = _input(
        "debugger",
        {"qa_task": {
            "verdict": "fail",
            "issues": [{"severity": "high", "description": "compile error"}],
        }},
    )
    fast = await svc._maybe_skip_debugger(task_input)
    assert fast is None, "verdict=fail must NOT short-circuit"


@pytest.mark.asyncio
async def test_runs_when_final_qa_warn(monkeypatch):
    monkeypatch.setattr(
        "services.workflow_svc.crud",
        _StubCrud({"qa_task": {"id": "qa_task", "kind": "final_qa"}}),
    )
    svc = WorkflowService()
    task_input = _input(
        "debugger",
        {"qa_task": {"verdict": "warn", "issues": [{"foo": "bar"}]}},
    )
    fast = await svc._maybe_skip_debugger(task_input)
    assert fast is None, "verdict=warn still has issues — debugger must run"


@pytest.mark.asyncio
async def test_runs_when_upstream_is_not_final_qa(monkeypatch):
    """Defensive: if for some reason the Debugger has no final_qa
    upstream (manually-rewritten DAG), don't fast-path."""
    monkeypatch.setattr(
        "services.workflow_svc.crud",
        _StubCrud({"other": {"id": "other", "kind": "regular"}}),
    )
    svc = WorkflowService()
    task_input = _input("debugger", {"other": {"some": "output"}})
    fast = await svc._maybe_skip_debugger(task_input)
    assert fast is None
