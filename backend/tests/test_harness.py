"""Quick smoke test for domain/harness state machine + DAG validator."""
from domain.harness.state_machine import HarnessStateMachine
from domain.harness.states import ProjectState, TaskState
from domain.qa.dag_validator import validate_dag
from domain.qa.output_validator import validate_output_schema


def test_state_machine_basic_flow():
    tasks = [
        {"id": "t1", "status": "pending", "deps": [], "kind": "regular"},
        {"id": "t2", "status": "pending", "deps": ["t1"], "kind": "regular"},
        {"id": "t3", "status": "pending", "deps": ["t1", "t2"], "kind": "final_qa"},
    ]

    h = HarnessStateMachine("p1", ProjectState.READY, tasks)

    # Start — only t1 should run (no deps)
    events = h.start()
    assert h.state == ProjectState.RUNNING
    running = [t["id"] for t in h.get_running_tasks()]
    assert running == ["t1"]

    # Complete t1 — t2 should start (deps met)
    events2 = h.complete_task("t1")
    running2 = [t["id"] for t in h.get_running_tasks()]
    assert running2 == ["t2"]

    # Complete t2 — t3 (final_qa) should start
    events3 = h.complete_task("t2")
    running3 = [t["id"] for t in h.get_running_tasks()]
    assert running3 == ["t3"]

    # Complete t3 — project should finalize
    events4 = h.complete_task("t3")
    assert h.state in (
        ProjectState.COMPLETED,
        ProjectState.COMPLETED_WITH_WARNINGS,
        ProjectState.COMPLETED_WITH_ISSUES,
    )
    print("State machine basic flow: PASSED")


def test_dag_validator():
    # Valid DAG
    tasks = [
        {"id": "t1", "deps": []},
        {"id": "t2", "deps": ["t1"]},
    ]
    errors = validate_dag(tasks)
    assert errors == [], f"Expected no errors, got {errors}"

    # Missing dependency
    tasks_bad = [
        {"id": "t1", "deps": ["t_missing"]},
    ]
    errors_bad = validate_dag(tasks_bad)
    assert any(e.kind == "missing_dependency" for e in errors_bad)
    print("DAG validator: PASSED")


def test_output_validator():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "score": {"type": "number"},
        },
        "required": ["name"],
    }

    # Valid
    errors = validate_output_schema({"name": "test", "score": 95}, schema)
    assert errors == []

    # Missing required
    errors2 = validate_output_schema({"score": 95}, schema)
    assert len(errors2) > 0

    # Free text mode
    errors3 = validate_output_schema({"anything": "goes"}, {})
    assert errors3 == []

    print("Output validator: PASSED")


if __name__ == "__main__":
    test_state_machine_basic_flow()
    test_dag_validator()
    test_output_validator()
    print("\nAll Phase 4 domain tests PASSED")
