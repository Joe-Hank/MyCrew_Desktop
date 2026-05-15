"""Stage-C smoke tests: workflow_svc._run_crew step orchestration.

Pure-Python tests that monkey-patch run_crew_step_with_crewai so we
don't need a real LLM. Validates:
  - Step walker visits each entry in agent_sequence in order
  - prev_step_payload from step N flows into step N+1 description
  - Sub-step IO files appear under <OUTPUT_DIR>/<pid>/<tid>/sub/
  - task.sub_step WS events broadcast in started→completed pairs
  - QA step's captured payload winds up under pop_output(parent_task_id)
  - PAUSED project state breaks the loop at a step boundary (Q7)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import services.workflow_svc as workflow_svc
from services.workflow_svc import WorkflowService, _extract_output_paths
from domain.harness.task_runner import TaskInput
from src.tools.builtin.local._output_capture import set_output, pop_output


# ── pure helpers ──────────────────────────────────────────────────

def test_extract_output_paths_from_examples():
    schema = {
        "properties": {
            "file_paths": {
                "examples": ["Assets/Sprites/a.png", "Assets/Sprites/b.png"]
            }
        }
    }
    assert _extract_output_paths(schema) == [
        "Assets/Sprites/a.png", "Assets/Sprites/b.png"
    ]


def test_extract_output_paths_from_const_string():
    schema = {
        "properties": {
            "file_path": {"const": "Assets/Scripts/Player.cs"}
        }
    }
    # singular file_path is NOT in the lookup keys for paths
    assert _extract_output_paths(schema) == []


def test_extract_output_paths_dedup_preserves_order():
    schema = {
        "properties": {
            "file_paths": {"examples": ["a", "b", "a", "c"]}
        }
    }
    assert _extract_output_paths(schema) == ["a", "b", "c"]


def test_extract_output_paths_empty_schema():
    assert _extract_output_paths({}) == []
    assert _extract_output_paths({"properties": {}}) == []


# ── _run_crew orchestration with mocked step runner ───────────────

@pytest.fixture
def crew_env(tmp_path, monkeypatch, fake_crud):
    """Patch the global crud module + redirect OUTPUT_DIR to tmp_path."""
    import infra.repo.crud as crud_mod
    # FakeCRUD doesn't expose every helper, but it has the ones _run_crew uses
    # (get_by_id, update_by_id, get_all).
    monkeypatch.setattr(workflow_svc, "crud", fake_crud)
    monkeypatch.setattr("services.crewai_runner.crud", fake_crud, raising=False)
    monkeypatch.setattr(crud_mod, "get_by_id", fake_crud.get_by_id, raising=False)
    monkeypatch.setattr(crud_mod, "update_by_id", fake_crud.update_by_id, raising=False)
    monkeypatch.setattr(crud_mod, "get_all", fake_crud.get_all, raising=False)
    monkeypatch.setattr(crud_mod, "delete_by_id", fake_crud.delete_by_id, raising=False)
    monkeypatch.setattr(crud_mod, "insert", fake_crud.insert, raising=False)

    # Redirect OUTPUT_DIR so sub-step IO writes into the tmp dir
    import bootstrap.paths as paths_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path / "output")

    # Seed minimal rows
    fake_crud.seed("projects", [{
        "id": "p1", "name": "test", "state": "ready",
        "root_path": str(tmp_path / "workspace"),
    }])
    fake_crud.seed("agents", [
        {"id": "agA", "role": "Art Director", "tool_ids": "[]"},
        {"id": "agB", "role": "ComfyUI Image Generator", "tool_ids": "[]"},
        {"id": "agC", "role": "QA Engineer", "tool_ids": "[]"},
    ])
    fake_crud.seed("crews", [{
        "id": "crewX",
        "name": "Art Crew",
        "agent_sequence": json.dumps([
            {"role": "head", "agent_id": "agA",
             "step_instructions": "spec it"},
            {"role": "executor", "agent_id": "agB",
             "step_instructions": "make it"},
            {"role": "qa", "agent_id": "agC",
             "step_instructions": "check it"},
        ]),
    }])
    fake_crud.seed("tasks", [{
        "id": "tk1",
        "project_id": "p1",
        "title": "T1",
        "detail": "do the thing",
        "performer_kind": "crew",
        "performer_id": "crewX",
        "output_schema": json.dumps({}),
    }])
    fake_crud.seed("llm_providers", [{"id": "prov", "type": "deepseek"}])
    fake_crud.seed("llm_models", [
        {"id": "m1", "provider_id": "prov", "model_name": "deepseek-flash"},
    ])
    return fake_crud


@pytest.mark.asyncio
async def test_run_crew_walks_sequence_in_order(crew_env, monkeypatch, tmp_path):
    visited: list[tuple[int, str, dict | None]] = []

    async def fake_run_step(**kwargs):
        i = kwargs["step_index"]
        prev = kwargs["prev_step_payload"]
        visited.append((i, kwargs["step_role"], prev))
        captured = {"step": i, "marker": f"out_of_step_{i}"}
        # QA step (final) — workflow_svc relies on emit_output capture
        # under the parent task_id key; mimic that.
        if kwargs["step_role"] == "qa":
            set_output(kwargs["parent_task_id"], captured)
        return f"raw text {i}", captured

    monkeypatch.setattr(
        "services.crewai_runner.run_crew_step_with_crewai",
        fake_run_step,
    )
    # Stub _resolve_agent_llm so we don't need real provider rows
    async def fake_resolve(_self, _agent):
        return "prov", "deepseek-flash"
    monkeypatch.setattr(WorkflowService, "_resolve_agent_llm", fake_resolve)
    # Stub broadcast to avoid WS dependency
    broadcasts: list[tuple[int, str]] = []
    async def fake_bcast(_self, _pid, _tid, idx, _role, _aid, _ar, status, **_):
        broadcasts.append((idx, status))
    monkeypatch.setattr(WorkflowService, "_broadcast_sub_step", fake_bcast)

    svc = WorkflowService()
    task_input = TaskInput(
        task_id="tk1", title="T1", detail="do the thing",
        agent_id="", output_schema={}, upstream_outputs={},
    )
    summary = await svc._run_crew("p1", "tk1", task_input, "crewX")

    # Visited all 3 steps in order
    assert [v[0] for v in visited] == [0, 1, 2]
    assert [v[1] for v in visited] == ["head", "executor", "qa"]
    # Step 0 saw no prev; subsequent steps saw the previous capture
    assert visited[0][2] is None
    assert visited[1][2] == {"step": 0, "marker": "out_of_step_0"}
    assert visited[2][2] == {"step": 1, "marker": "out_of_step_1"}
    # Summary lists each step
    assert "Step 1/3" in summary and "Step 3/3" in summary
    # Broadcasts: started+completed for each step → 6 events
    assert broadcasts == [
        (0, "started"), (0, "completed"),
        (1, "started"), (1, "completed"),
        (2, "started"), (2, "completed"),
    ]
    # QA step's capture is under the parent task_id key
    final = pop_output("tk1")
    assert final == {"step": 2, "marker": "out_of_step_2"}


@pytest.mark.asyncio
async def test_run_crew_writes_sub_step_io(crew_env, monkeypatch, tmp_path):
    async def fake_run_step(**kwargs):
        return f"raw text {kwargs['step_index']}", {"echo": kwargs["step_index"]}
    monkeypatch.setattr(
        "services.crewai_runner.run_crew_step_with_crewai", fake_run_step)
    async def fake_resolve(_self, _agent):
        return "prov", "deepseek-flash"
    monkeypatch.setattr(WorkflowService, "_resolve_agent_llm", fake_resolve)
    async def fake_bcast(*a, **kw): pass
    monkeypatch.setattr(WorkflowService, "_broadcast_sub_step", fake_bcast)

    svc = WorkflowService()
    task_input = TaskInput(
        task_id="tk1", title="T1", detail="", agent_id="",
        output_schema={}, upstream_outputs={},
    )
    await svc._run_crew("p1", "tk1", task_input, "crewX")

    sub_dir = tmp_path / "output" / "p1" / "tk1" / "sub"
    assert (sub_dir / "0_head_in.json").exists()
    assert (sub_dir / "0_head_out.json").exists()
    assert (sub_dir / "0_head_out.md").exists()
    assert (sub_dir / "1_executor_out.json").exists()
    assert (sub_dir / "2_qa_out.json").exists()

    # Check structured content
    out0 = json.loads((sub_dir / "0_head_out.json").read_text(encoding="utf-8"))
    assert out0["step_index"] == 0
    assert out0["captured"] == {"echo": 0}
    in1 = json.loads((sub_dir / "1_executor_in.json").read_text(encoding="utf-8"))
    assert in1["prev_step_payload"] == {"echo": 0}


@pytest.mark.asyncio
async def test_run_crew_pauses_at_step_boundary(crew_env, monkeypatch, tmp_path):
    """Q7: when the project is paused, the loop exits cleanly before
    the next step's kickoff — the in-flight step still finishes."""
    from domain.harness.state_machine import HarnessStateMachine
    from domain.harness.states import ProjectState

    step_calls = []
    async def fake_run_step(**kwargs):
        step_calls.append(kwargs["step_index"])
        return "raw", {"step": kwargs["step_index"]}
    monkeypatch.setattr(
        "services.crewai_runner.run_crew_step_with_crewai", fake_run_step)
    async def fake_resolve(_self, _agent): return "prov", "deepseek-flash"
    monkeypatch.setattr(WorkflowService, "_resolve_agent_llm", fake_resolve)
    async def fake_bcast(*a, **kw): pass
    monkeypatch.setattr(WorkflowService, "_broadcast_sub_step", fake_bcast)

    svc = WorkflowService()
    # Inject a paused harness
    harness = HarnessStateMachine("p1", ProjectState.PAUSED, [
        {"id": "tk1", "status": "pending", "deps": [], "kind": "regular"},
    ])
    svc._active["p1"] = harness

    task_input = TaskInput(
        task_id="tk1", title="T1", detail="", agent_id="",
        output_schema={}, upstream_outputs={},
    )
    summary = await svc._run_crew("p1", "tk1", task_input, "crewX")

    # Loop exits at first boundary check → 0 step kickoffs
    assert step_calls == []
    assert "paused" in summary.lower()
