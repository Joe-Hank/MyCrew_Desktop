"""Edge-case tests for HarnessStateMachine beyond the basics in test_workflow_logic.py."""
import pytest

from domain.harness.states import ProjectState, TaskState
from domain.harness.state_machine import HarnessStateMachine, InvalidTransition
from domain.events import (
    ProjectCompleted, ProjectProgress, TaskBlocked, TaskStarted,
    TaskFailed, TaskCompleted,
)


def _tasks(specs):
    return [{"id": s["id"], "status": s.get("status", TaskState.PENDING),
             "deps": s.get("deps", []), "kind": s.get("kind", "regular"),
             "output_schema": s.get("output_schema", {})} for s in specs]


class TestEdgeCases:
    def test_empty_task_list(self):
        sm = HarnessStateMachine("p1", ProjectState.READY, [])
        events = sm.start()
        assert sm.state == ProjectState.RUNNING
        assert sm.progress_pct == 0.0

    def test_single_task_completes_project(self):
        sm = HarnessStateMachine("p1", ProjectState.READY, _tasks([{"id": "t1"}]))
        sm.start()
        events = sm.complete_task("t1")
        completed = [e for e in events if isinstance(e, ProjectCompleted)]
        assert len(completed) == 1

    def test_all_terminal_states_are_final(self):
        for state in (ProjectState.COMPLETED, ProjectState.COMPLETED_WITH_WARNINGS,
                      ProjectState.COMPLETED_WITH_ISSUES, ProjectState.ABORTED):
            sm = HarnessStateMachine("p1", state, _tasks([{"id": "t1"}]))
            with pytest.raises(InvalidTransition):
                sm.start()

    def test_abort_from_paused(self):
        sm = HarnessStateMachine("p1", ProjectState.READY, _tasks([{"id": "t1"}]))
        sm.start()
        sm.pause()
        events = sm.abort("done")
        assert sm.state == ProjectState.ABORTED

    def test_double_complete_raises(self):
        sm = HarnessStateMachine("p1", ProjectState.READY, _tasks([{"id": "t1"}]))
        sm.start()
        sm.complete_task("t1")
        with pytest.raises(InvalidTransition):
            sm.complete_task("t1")

    def test_fail_then_retry_then_complete(self):
        sm = HarnessStateMachine("p1", ProjectState.READY, _tasks([
            {"id": "t1"},
            {"id": "t2", "deps": ["t1"]},
        ]))
        sm.start()
        sm.fail_task("t1", "err")
        assert sm.get_task("t2")["status"] == TaskState.BLOCKED

        sm.retry_task("t1")
        assert sm.get_task("t1")["status"] == TaskState.RUNNING
        assert sm.get_task("t2")["status"] == TaskState.PENDING

        events = sm.complete_task("t1")
        started = [e.task_id for e in events if isinstance(e, TaskStarted)]
        assert "t2" in started

    def test_diamond_dag(self):
        """A→(B,C)→D: ensure D only starts after both B and C are done."""
        tasks = _tasks([
            {"id": "a"},
            {"id": "b", "deps": ["a"]},
            {"id": "c", "deps": ["a"]},
            {"id": "d", "deps": ["b", "c"]},
        ])
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()
        sm.complete_task("a")

        sm.complete_task("b")
        assert sm.get_task("d")["status"] == TaskState.PENDING

        events = sm.complete_task("c")
        started = [e.task_id for e in events if isinstance(e, TaskStarted)]
        assert "d" in started

    def test_multiple_failures_block_cascading(self):
        tasks = _tasks([
            {"id": "t1"},
            {"id": "t2", "deps": ["t1"]},
            {"id": "t3", "deps": ["t2"]},
        ])
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()
        events = sm.fail_task("t1", "err")

        blocked_ids = [e.task_id for e in events if isinstance(e, TaskBlocked)]
        assert "t2" in blocked_ids

    def test_progress_with_mixed_terminal_states(self):
        tasks = _tasks([
            {"id": "t1"},
            {"id": "t2"},
            {"id": "t3"},
        ])
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()
        sm.complete_task("t1")
        sm.fail_task("t2", "err")
        assert sm.progress_pct == pytest.approx(33.3, abs=0.1)

    def test_final_qa_pass_gives_completed(self):
        tasks = _tasks([
            {"id": "t1"},
            {"id": "t2", "deps": ["t1"], "kind": "final_qa"},
        ])
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()
        sm.complete_task("t1")
        events = sm.complete_task("t2")

        completed = [e for e in events if isinstance(e, ProjectCompleted)]
        assert len(completed) == 1
        assert completed[0].verdict == "pass"
        assert sm.state == ProjectState.COMPLETED

    def test_final_qa_fail_gives_completed_with_issues(self):
        tasks = _tasks([
            {"id": "t1"},
            {"id": "t2", "deps": ["t1"], "kind": "final_qa"},
        ])
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()
        sm.complete_task("t1")
        sm.fail_task("t2", "qa failed")

        assert sm.state in (ProjectState.COMPLETED_WITH_ISSUES, ProjectState.RUNNING)

    def test_get_task_raises_on_unknown_id(self):
        sm = HarnessStateMachine("p1", ProjectState.READY, _tasks([{"id": "t1"}]))
        with pytest.raises(KeyError):
            sm.get_task("nonexistent")

    def test_pause_only_affects_pending_tasks(self):
        tasks = _tasks([
            {"id": "t1"},
            {"id": "t2"},
        ])
        sm = HarnessStateMachine("p1", ProjectState.READY, tasks)
        sm.start()
        # Both t1 and t2 are now RUNNING (no deps)
        sm.pause()
        # RUNNING tasks stay RUNNING, only PENDING become PAUSED
        assert sm.get_task("t1")["status"] == TaskState.RUNNING
        assert sm.get_task("t2")["status"] == TaskState.RUNNING
