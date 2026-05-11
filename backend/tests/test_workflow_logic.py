"""Tests for workflow logic — state machine transitions, DAG validation, output validation."""
import pytest

from domain.harness.states import ProjectState, TaskState
from domain.harness.state_machine import HarnessStateMachine, InvalidTransition
from domain.qa.dag_validator import validate_dag
from domain.qa.output_validator import validate_output_schema
from domain.events import (
    ProjectStarted, ProjectPaused, ProjectResumed, ProjectCompleted,
    TaskStarted, TaskCompleted, TaskFailed, TaskPaused, TaskBlocked,
    TaskValidationFailed, ProjectProgress,
)


# ── Fixtures ───────────────────────────────────────────────────

def _make_tasks(specs: list[dict]) -> list[dict]:
    """Helper to create task dicts from specs."""
    tasks = []
    for s in specs:
        tasks.append({
            "id": s["id"],
            "status": s.get("status", TaskState.PENDING),
            "deps": s.get("deps", []),
            "kind": s.get("kind", "regular"),
            "output_schema": s.get("output_schema", {}),
        })
    return tasks


def _simple_linear_tasks():
    """A→B→C linear chain."""
    return _make_tasks([
        {"id": "t1"},
        {"id": "t2", "deps": ["t1"]},
        {"id": "t3", "deps": ["t2"], "kind": "final_qa"},
    ])


def _parallel_tasks():
    """Fork-join: A→(B, C)→D."""
    return _make_tasks([
        {"id": "t1"},
        {"id": "t2", "deps": ["t1"]},
        {"id": "t3", "deps": ["t1"]},
        {"id": "t4", "deps": ["t2", "t3"]},
    ])


# ── Project State Machine ─────────────────────────────────────

class TestProjectStateMachine:
    def test_start_from_ready(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        events = sm.start()

        assert sm.state == ProjectState.RUNNING
        assert any(isinstance(e, ProjectStarted) for e in events)
        # t1 should be activated (no deps)
        assert any(isinstance(e, TaskStarted) and e.task_id == "t1" for e in events)

    def test_pause_from_running(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()

        events = sm.pause()
        assert sm.state == ProjectState.PAUSED
        assert any(isinstance(e, ProjectPaused) for e in events)

    def test_resume_from_paused(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()
        sm.pause()

        events = sm.resume()
        assert sm.state == ProjectState.RUNNING
        assert any(isinstance(e, ProjectResumed) for e in events)

    def test_cannot_start_when_running(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()

        with pytest.raises(InvalidTransition):
            sm.start()

    def test_abort(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()

        events = sm.abort("user cancelled")
        assert sm.state == ProjectState.ABORTED


# ── Task State Transitions ────────────────────────────────────

class TestTaskTransitions:
    def test_linear_completion(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()

        # Complete t1 → t2 should start
        events = sm.complete_task("t1")
        assert any(isinstance(e, TaskCompleted) and e.task_id == "t1" for e in events)
        assert any(isinstance(e, TaskStarted) and e.task_id == "t2" for e in events)

        # Complete t2 → t3 (final_qa) should start
        events = sm.complete_task("t2")
        assert any(isinstance(e, TaskStarted) and e.task_id == "t3" for e in events)

        # Complete t3 → project should complete
        events = sm.complete_task("t3")
        assert any(isinstance(e, ProjectCompleted) for e in events)
        assert sm.state in (
            ProjectState.COMPLETED,
            ProjectState.COMPLETED_WITH_WARNINGS,
            ProjectState.COMPLETED_WITH_ISSUES,
        )

    def test_parallel_fork_join(self):
        tasks = _parallel_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()

        # t1 running
        events = sm.complete_task("t1")
        started_ids = {e.task_id for e in events if isinstance(e, TaskStarted)}
        assert "t2" in started_ids
        assert "t3" in started_ids

        # Complete t2, t4 should NOT start yet (still waiting for t3)
        events = sm.complete_task("t2")
        started_ids = {e.task_id for e in events if isinstance(e, TaskStarted)}
        assert "t4" not in started_ids

        # Complete t3, NOW t4 should start
        events = sm.complete_task("t3")
        started_ids = {e.task_id for e in events if isinstance(e, TaskStarted)}
        assert "t4" in started_ids

    def test_task_failure_blocks_downstream(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()

        events = sm.fail_task("t1", "LLM timeout")
        assert any(isinstance(e, TaskFailed) and e.task_id == "t1" for e in events)
        assert any(isinstance(e, TaskBlocked) and e.task_id == "t2" for e in events)

    def test_validation_failure(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()

        events = sm.validation_fail_task("t1", ["field 'name' is required"])
        assert any(isinstance(e, TaskValidationFailed) for e in events)

    def test_retry_after_failure(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()
        sm.fail_task("t1", "error")

        events = sm.retry_task("t1")
        assert any(isinstance(e, TaskStarted) and e.task_id == "t1" for e in events)

    def test_progress_tracking(self):
        tasks = _simple_linear_tasks()
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()

        assert sm.progress_pct == 0.0
        sm.complete_task("t1")
        assert sm.progress_pct == pytest.approx(33.3, abs=0.1)
        sm.complete_task("t2")
        assert sm.progress_pct == pytest.approx(66.7, abs=0.1)


# ── DAG Validation ─────────────────────────────────────────────

class TestDagValidation:
    def test_valid_linear_dag(self):
        tasks = _simple_linear_tasks()
        errors = validate_dag(tasks)
        assert len(errors) == 0

    def test_valid_parallel_dag(self):
        tasks = _parallel_tasks()
        errors = validate_dag(tasks)
        assert len(errors) == 0

    def test_cycle_detection(self):
        tasks = _make_tasks([
            {"id": "t1", "deps": ["t3"]},
            {"id": "t2", "deps": ["t1"]},
            {"id": "t3", "deps": ["t2"]},
        ])
        errors = validate_dag(tasks)
        assert len(errors) > 0
        assert any("cycle" in e.message.lower() or "loop" in e.message.lower()
                    or "拓扑" in e.message or "环" in e.message
                    for e in errors)

    def test_missing_dep_reference(self):
        tasks = _make_tasks([
            {"id": "t1"},
            {"id": "t2", "deps": ["t_nonexistent"]},
        ])
        errors = validate_dag(tasks)
        assert len(errors) > 0


# ── Output Schema Validation ──────────────────────────────────

class TestOutputValidation:
    def test_valid_output(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "score": {"type": "number"},
            },
            "required": ["name", "score"],
        }
        data = {"name": "test", "score": 95}
        errors = validate_output_schema(data, schema)
        assert len(errors) == 0

    def test_invalid_output_missing_required(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "score": {"type": "number"},
            },
            "required": ["name", "score"],
        }
        data = {"name": "test"}  # missing score
        errors = validate_output_schema(data, schema)
        assert len(errors) > 0

    def test_empty_schema_always_passes(self):
        errors = validate_output_schema({"anything": "goes"}, {})
        assert len(errors) == 0

    def test_type_mismatch(self):
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
            "required": ["count"],
        }
        data = {"count": "not_a_number"}
        errors = validate_output_schema(data, schema)
        assert len(errors) > 0
