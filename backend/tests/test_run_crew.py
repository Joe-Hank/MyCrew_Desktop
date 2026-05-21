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


# ── Stage 2: script_qa branch ─────────────────────────────────────

@pytest.mark.asyncio
async def test_run_crew_script_qa_branch_skips_llm(
    crew_env, monkeypatch, tmp_path, fake_crud,
):
    """When the QA step is marked `kind='script_qa'`, run_crew dispatches
    `services.qa_script.verify_task_qa` instead of run_crew_step_with_crewai.
    Verifies:
      - LLM runner not invoked for the QA step
      - Captured payload landed under pop_output(parent_task_id)
      - WS broadcast fired completed (not failed) for a passing QA
      - Sub-step IO files written under sub/2_qa_*
    """
    # Swap the QA step in our seeded Crew to script_qa.
    crew_row = await fake_crud.get_by_id("crews", "crewX")
    seq = json.loads(crew_row["agent_sequence"])
    seq[2]["kind"] = "script_qa"
    crew_row["agent_sequence"] = json.dumps(seq)

    # The script reads task.output_paths off the row + checks files on
    # disk. Wire a single PNG and point the task at it.
    workspace = tmp_path / "workspace"
    (workspace / "Assets" / "Sprites").mkdir(parents=True)
    from PIL import Image
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(
        workspace / "Assets" / "Sprites" / "ok.png", "PNG",
    )
    task_row = await fake_crud.get_by_id("tasks", "tk1")
    task_row["output_paths"] = json.dumps(["Assets/Sprites/ok.png"])
    task_row["output_schema"] = json.dumps({
        "properties": {"width": {"const": 64}, "height": {"const": 64}},
    })

    # Patch qa_script's crud handle to our FakeCRUD too — it's imported
    # at function entry inside the script_qa branch.
    import services.qa_script as qa_script_mod
    monkeypatch.setattr(qa_script_mod, "crud", fake_crud)

    # LLM runner — should NOT be called for the QA step. We track all
    # calls; only steps 0 and 1 should land here.
    llm_calls: list[int] = []
    async def fake_run_step(**kwargs):
        llm_calls.append(kwargs["step_index"])
        return f"raw {kwargs['step_index']}", {"step": kwargs["step_index"]}
    monkeypatch.setattr(
        "services.crewai_runner.run_crew_step_with_crewai", fake_run_step)
    async def fake_resolve(_self, _agent): return "prov", "deepseek-flash"
    monkeypatch.setattr(WorkflowService, "_resolve_agent_llm", fake_resolve)
    broadcasts: list[tuple[int, str]] = []
    async def fake_bcast(_self, _pid, _tid, idx, _role, _aid, _ar, status, **_):
        broadcasts.append((idx, status))
    monkeypatch.setattr(WorkflowService, "_broadcast_sub_step", fake_bcast)

    svc = WorkflowService()
    task_input = TaskInput(
        task_id="tk1", title="T1", detail="透明背景",
        agent_id="", output_schema={"properties": {"width": {"const": 64}, "height": {"const": 64}}},
        upstream_outputs={},
    )
    summary = await svc._run_crew("p1", "tk1", task_input, "crewX")

    # LLM only ran on head + executor — script QA bypassed it.
    assert llm_calls == [0, 1]
    # QA capture available under parent task_id key.
    final = pop_output("tk1")
    assert final is not None
    assert final["verdict"] == "pass"
    assert final["file_paths"] == ["Assets/Sprites/ok.png"]
    # Broadcast pattern: QA step (idx=2) completes (passing verdict).
    assert (2, "started") in broadcasts
    assert (2, "completed") in broadcasts
    assert (2, "failed") not in broadcasts
    # Sub-step IO files written.
    sub_dir = tmp_path / "output" / "p1" / "tk1" / "sub"
    assert (sub_dir / "2_qa_in.json").exists()
    assert (sub_dir / "2_qa_out.json").exists()
    out2 = json.loads((sub_dir / "2_qa_out.json").read_text(encoding="utf-8"))
    assert out2["captured"]["verdict"] == "pass"
    # Summary mentions the scripted step.
    assert "script" in summary.lower()


@pytest.mark.asyncio
async def test_run_crew_script_qa_failure_broadcasts_fail(
    crew_env, monkeypatch, tmp_path, fake_crud,
):
    """When the script QA finds violations (e.g. file missing), the
    captured verdict is 'fail' AND the sub_step WS event reports
    'failed' so the canvas card turns red."""
    crew_row = await fake_crud.get_by_id("crews", "crewX")
    seq = json.loads(crew_row["agent_sequence"])
    seq[2]["kind"] = "script_qa"
    crew_row["agent_sequence"] = json.dumps(seq)

    task_row = await fake_crud.get_by_id("tasks", "tk1")
    # Output path points at a file that doesn't exist.
    task_row["output_paths"] = json.dumps(["Assets/Sprites/missing.png"])
    task_row["output_schema"] = json.dumps({})

    import services.qa_script as qa_script_mod
    monkeypatch.setattr(qa_script_mod, "crud", fake_crud)

    async def fake_run_step(**kwargs):
        return f"raw {kwargs['step_index']}", {"step": kwargs["step_index"]}
    monkeypatch.setattr(
        "services.crewai_runner.run_crew_step_with_crewai", fake_run_step)
    async def fake_resolve(_self, _agent): return "prov", "deepseek-flash"
    monkeypatch.setattr(WorkflowService, "_resolve_agent_llm", fake_resolve)
    broadcasts: list[tuple[int, str, str | None]] = []
    async def fake_bcast(_self, _pid, _tid, idx, _role, _aid, _ar, status, **kw):
        broadcasts.append((idx, status, kw.get("error")))
    monkeypatch.setattr(WorkflowService, "_broadcast_sub_step", fake_bcast)

    svc = WorkflowService()
    task_input = TaskInput(
        task_id="tk1", title="T1", detail="",
        agent_id="", output_schema={}, upstream_outputs={},
    )
    summary = await svc._run_crew("p1", "tk1", task_input, "crewX")

    final = pop_output("tk1")
    assert final["verdict"] == "fail"
    assert any("不存在" in i for i in final["issues"])
    # QA step broadcast failed with an error excerpt.
    qa_events = [e for e in broadcasts if e[0] == 2]
    assert any(s == "failed" and err for _, s, err in qa_events)


# ── 2026-05-20: chain-of-tools safety fixes ───────────────────────

@pytest.mark.asyncio
async def test_run_crew_halts_when_head_captured_is_none(
    crew_env, monkeypatch, tmp_path,
):
    """A Head step that never invokes emit_output (the Butcher debug
    case: LLM dumped `Action: write_file` as text) used to let the
    Crew continue running Executor + TA + QA empty-handed. Verify
    workflow_svc now halts at the Head boundary with a precise
    diagnostic error chain."""
    async def fake_run_step(**kwargs):
        # Simulate the bug: agent outputs ReAct text mentioning a tool
        # OTHER than emit_output, so rescue cannot recover, and captured
        # stays None.
        if kwargs["step_index"] == 0:
            return ('Action: write_file\nAction Input: {"path":"x","content":""}', None)
        return ("raw", {"verdict": "pass"})

    monkeypatch.setattr(
        "services.crewai_runner.run_crew_step_with_crewai", fake_run_step)
    async def fake_resolve(_self, _agent): return "prov", "deepseek-flash"
    monkeypatch.setattr(WorkflowService, "_resolve_agent_llm", fake_resolve)
    async def fake_bcast(*a, **kw): pass
    monkeypatch.setattr(WorkflowService, "_broadcast_sub_step", fake_bcast)

    svc = WorkflowService()
    task_input = TaskInput(
        task_id="tk1", title="T1", detail="",
        agent_id="", output_schema={}, upstream_outputs={},
    )
    with pytest.raises(RuntimeError) as exc_info:
        await svc._run_crew("p1", "tk1", task_input, "crewX")

    err = str(exc_info.value)
    assert "emit_output" in err


@pytest.mark.asyncio
async def test_run_crew_rescues_react_emit_output_text(
    crew_env, monkeypatch, tmp_path,
):
    """When the LLM did output `Action: emit_output\nAction Input: {...}`
    as plain text (instead of a proper tool call), the rescue path
    extracts the JSON payload and treats it as if emit_output had
    been invoked. Crew should NOT halt; downstream steps continue."""
    rescue_text = (
        "Thought: I have the prompts ready, will emit now.\n"
        'Action: emit_output\n'
        'Action Input: {"payload": {"width": 64, "height": 64, '
        '"prompts": {"a.png": {"positive_prompt": "x"}}}}'
    )
    visited_prev: list[dict | None] = []

    async def fake_run_step(**kwargs):
        visited_prev.append(kwargs.get("prev_step_payload"))
        if kwargs["step_index"] == 0:
            return (rescue_text, None)
        return ("raw", {"verdict": "pass", "step": kwargs["step_index"]})

    monkeypatch.setattr(
        "services.crewai_runner.run_crew_step_with_crewai", fake_run_step)
    async def fake_resolve(_self, _agent): return "prov", "deepseek-flash"
    monkeypatch.setattr(WorkflowService, "_resolve_agent_llm", fake_resolve)
    async def fake_bcast(*a, **kw): pass
    monkeypatch.setattr(WorkflowService, "_broadcast_sub_step", fake_bcast)

    svc = WorkflowService()
    task_input = TaskInput(
        task_id="tk1", title="T1", detail="",
        agent_id="", output_schema={}, upstream_outputs={},
    )
    summary = await svc._run_crew("p1", "tk1", task_input, "crewX")

    assert visited_prev[1] is not None, visited_prev
    assert visited_prev[1]["width"] == 64
    assert "prompts" in visited_prev[1]
    assert "Step 1/3" in summary and "Step 3/3" in summary


def test_rescue_react_emit_output_strips_payload_wrapper():
    from services.workflow_svc import _rescue_react_emit_output
    text = (
        'Some thinking.\n'
        'Action: emit_output\n'
        'Action Input: {"payload": {"verdict": "pass", "file_paths": ["x"]}}\n'
        'Some trailing prose.'
    )
    out = _rescue_react_emit_output(text)
    assert out == {"verdict": "pass", "file_paths": ["x"]}


def test_rescue_react_emit_output_returns_none_for_wrong_tool():
    """The rescue must NOT salvage a write_file call as if it were
    emit_output — that would mask the wrong-tool mistake."""
    from services.workflow_svc import _rescue_react_emit_output
    text = 'Action: write_file\nAction Input: {"path":"x","content":""}'
    assert _rescue_react_emit_output(text) is None


def test_rescue_react_emit_output_handles_no_payload_wrapper():
    """When the action input is the bare payload dict (no `payload:`
    nesting), return it as-is."""
    from services.workflow_svc import _rescue_react_emit_output
    text = (
        'Action: emit_output\n'
        'Action Input: {"verdict": "pass", "issues": []}'
    )
    out = _rescue_react_emit_output(text)
    assert out == {"verdict": "pass", "issues": []}


@pytest.mark.asyncio
async def test_fanout_marks_children_failed_on_empty_captured(
    crew_env, monkeypatch, tmp_path, fake_crud,
):
    """Fan-out children whose emit_output is never invoked (captured=None)
    used to land as `status=done`, painting the canvas green while the
    parent QA later reports "files don't exist". After fix:
      - status = failed
      - last_error explains "child emit_output 未被调用"
      - result.verdict = fail (propagates to parent QA aggregate)
      - failed_count increments (drives the canvas fan-out badge red)
    """
    # Wire a child into the parent.
    fake_crud.seed("tasks", [{
        "id": "child1", "project_id": "p1",
        "title": "child", "detail": "",
        "kind": "regular",
        "performer_kind": "crew", "performer_id": "crewX",
        "output_schema": json.dumps({}),
        "output_paths": json.dumps(["Assets/Sprites/x.png"]),
        "parent_task_id": "tk1",
        "parent_step_index": None,
        "status": "pending",
        "deps": json.dumps(["tk1"]),
    }])

    # Mark step 1 of the Crew as a fanout step so the runner takes the
    # fan-out branch for that step.
    crew_row = await fake_crud.get_by_id("crews", "crewX")
    seq = json.loads(crew_row["agent_sequence"])
    seq[1]["fanout"] = {"concurrency_cap": 1}
    seq[2]["kind"] = "script_qa"  # let QA finish without LLM
    crew_row["agent_sequence"] = json.dumps(seq)

    # Point qa_script's crud at our fake DB.
    import services.qa_script as qa_script_mod
    monkeypatch.setattr(qa_script_mod, "crud", fake_crud)

    async def fake_run_step(**kwargs):
        # Head produces an OK spec; fan-out executor returns no captured
        # for every child (the bug we're testing protects against).
        if kwargs["step_role"] == "head":
            return ("ok", {"width": 64, "height": 64, "prompts": {}})
        return (
            "Thought: I'm just thinking. No tool call.\n"
            "Thought: Still thinking.",
            None,
        )

    monkeypatch.setattr(
        "services.crewai_runner.run_crew_step_with_crewai", fake_run_step)
    async def fake_resolve(_self, _agent): return "prov", "deepseek-flash"
    monkeypatch.setattr(WorkflowService, "_resolve_agent_llm", fake_resolve)
    async def fake_bcast(*a, **kw): pass
    monkeypatch.setattr(WorkflowService, "_broadcast_sub_step", fake_bcast)
    async def fake_parallel(*a, **kw): pass
    monkeypatch.setattr(
        WorkflowService, "_broadcast_parallel_progress", fake_parallel)

    svc = WorkflowService()
    task_input = TaskInput(
        task_id="tk1", title="T1", detail="",
        agent_id="", output_schema={}, upstream_outputs={},
    )
    # Don't care about the outer summary; what we want is the child row
    # post-fan-out + the aggregate.
    try:
        await svc._run_crew("p1", "tk1", task_input, "crewX")
    except Exception:
        # QA may halt the Crew depending on the script's view of disk.
        # The child status is what we're verifying.
        pass

    child = await fake_crud.get_by_id("tasks", "child1")
    assert child["status"] == "failed", child
    assert "emit_output 未被调用" in (child.get("last_error") or "")
    assert child.get("last_error_kind") == "no_output"


# ── 2026-05-20: final-answer JSON rescue (TA case) ────────────────

def test_rescue_react_emit_output_picks_last_shaped_json():
    """When agent ends with `I now know the final answer` + fenced JSON,
    CrewAI returns raw text without invoking emit_output. The rescue
    must walk every balanced {...} and pick the LAST one whose keys
    match the emit_output shape — earlier scratchpad JSONs are skipped."""
    from services.workflow_svc import _rescue_react_emit_output
    text = (
        'Thought: trying a config\n'
        '{"some_scratch": 1, "irrelevant": 2}\n'
        'OK, real answer now.\n'
        'I now know the final answer\n'
        '```json\n'
        '{"file_paths": ["a.png", "b.png"], "issues": ["x"]}\n'
        '```\n'
    )
    out = _rescue_react_emit_output(text)
    assert out == {"file_paths": ["a.png", "b.png"], "issues": ["x"]}


def test_rescue_react_emit_output_rejects_write_file_json():
    """A bare `{"path": ..., "content": ...}` JSON should NOT be rescued
    as emit_output — that's a write_file argument, no emit_output
    shape keys."""
    from services.workflow_svc import _rescue_react_emit_output
    text = (
        'I will write the file.\n'
        '```json\n'
        '{"path": "Assets/foo.png", "content": "", "mode": "overwrite"}\n'
        '```\n'
    )
    assert _rescue_react_emit_output(text) is None


def test_rescue_react_emit_output_unwraps_payload_in_final_answer():
    """If the agent's final-answer JSON itself wraps the data under a
    `payload` key (older convention), the rescue still strips it so the
    downstream contract sees the unwrapped shape."""
    from services.workflow_svc import _rescue_react_emit_output
    text = (
        'I now know the final answer.\n'
        '{"payload": {"file_paths": ["x"], "verdict": "pass"}}'
    )
    out = _rescue_react_emit_output(text)
    assert out == {"file_paths": ["x"], "verdict": "pass"}


def test_rescue_react_emit_output_unwraps_openai_tool_call_wire_shape():
    """Empirically observed with Qwen-plus (2026-05-21): when CrewAI's
    ReAct loop fails to route a tool call natively, the agent occasionally
    dumps the OpenAI tool_calls wire format as its Final Answer instead —
    `{"name": "emit_output", "arguments": {"payload": {...}}}`. The rescue
    must drill through BOTH the OpenAI wrapper and the payload wrapper to
    recover the agent's intended emit_output payload."""
    from services.workflow_svc import _rescue_react_emit_output
    text = (
        '{"name": "emit_output", "arguments": '
        '{"payload": {"file_paths": ["Assets/Scripts/Foo.cs"], '
        '"coverage": {"Foo.cs": 5}}}}'
    )
    out = _rescue_react_emit_output(text)
    assert out == {
        "file_paths": ["Assets/Scripts/Foo.cs"],
        "coverage": {"Foo.cs": 5},
    }


def test_rescue_react_emit_output_ignores_openai_wrapper_for_other_tools():
    """The OpenAI tool-call unwrap branch must only fire for
    `name == "emit_output"` — otherwise we'd accidentally salvage a
    `write_file` or `find_in_file` argument JSON as if the agent meant
    emit_output, masking a wrong-tool mistake."""
    from services.workflow_svc import _rescue_react_emit_output
    text = (
        '{"name": "write_file", "arguments": '
        '{"path": "Assets/foo.cs", "content": "..."}}'
    )
    # write_file arguments don't carry any emit_output shape keys, so
    # neither the OpenAI unwrap nor the shape check should promote it.
    assert _rescue_react_emit_output(text) is None


def test_rescue_react_emit_output_butcher_ta_case():
    """Verbatim repro of the 2026-05-20 Butcher debug project failure:
    Technical Artist agent dumped a valid emit_output payload as a
    markdown-fenced JSON block + 'I now know the final answer' marker.
    CrewAI returned raw text, captured=None. The rescue should
    recover the agent's intended payload."""
    from services.workflow_svc import _rescue_react_emit_output
    text = (
        '好，现在设置导入属性... (long thought paragraphs) ...\n\n'
        '```json\n'
        '{\n'
        '  "file_paths": [\n'
        '    "Assets/Sprites/Butcher_64.png",\n'
        '    "Assets/Sprites/Butcher_512.png",\n'
        '    "Assets/Sprites/Butcher_1080.png"\n'
        '  ],\n'
        '  "issues": [\n'
        '    "ComfyUI MCP still unavailable",\n'
        '    "Toolset lacks ability to configure TextureImporter"\n'
        '  ]\n'
        '}\n'
        '```\n'
        'I now know the final answer\n'
    )
    out = _rescue_react_emit_output(text)
    assert out is not None
    assert len(out["file_paths"]) == 3
    assert "Butcher_64.png" in out["file_paths"][0]
    assert len(out["issues"]) == 2


# ── 2026-05-20: file-existence rescue (Unity Developer case) ──────

def test_rescue_by_file_existence_all_present(tmp_path):
    from services.workflow_svc import _rescue_by_file_existence
    (tmp_path / "Assets" / "Scripts").mkdir(parents=True)
    (tmp_path / "Assets" / "Scripts" / "A.cs").write_text("class A {}")
    (tmp_path / "Assets" / "Scripts" / "B.cs").write_text("class B {}")
    out = _rescue_by_file_existence(
        ["Assets/Scripts/A.cs", "Assets/Scripts/B.cs"],
        str(tmp_path),
    )
    assert out is not None
    assert out["file_paths"] == ["Assets/Scripts/A.cs", "Assets/Scripts/B.cs"]
    assert "已在磁盘上存在" in out["summary"]


def test_rescue_by_file_existence_missing_returns_none(tmp_path):
    from services.workflow_svc import _rescue_by_file_existence
    out = _rescue_by_file_existence(
        ["Assets/Scripts/missing.cs"], str(tmp_path),
    )
    assert out is None


def test_rescue_by_file_existence_empty_file_returns_none(tmp_path):
    from services.workflow_svc import _rescue_by_file_existence
    (tmp_path / "x.cs").touch()  # 0 bytes
    out = _rescue_by_file_existence(["x.cs"], str(tmp_path))
    assert out is None


def test_rescue_by_file_existence_path_escape_refused(tmp_path):
    from services.workflow_svc import _rescue_by_file_existence
    out = _rescue_by_file_existence(["../../etc/passwd"], str(tmp_path))
    assert out is None


def test_rescue_by_file_existence_no_root_returns_none():
    from services.workflow_svc import _rescue_by_file_existence
    out = _rescue_by_file_existence(["x.cs"], None)
    assert out is None


def test_rescue_by_file_existence_no_paths_returns_none(tmp_path):
    from services.workflow_svc import _rescue_by_file_existence
    out = _rescue_by_file_existence([], str(tmp_path))
    assert out is None


# ── 2026-05-21: server-side disk truth check (Layer 2 enforcement) ──
# These lock down the behavior that catches "agent ships ExecutorOutput
# with file_paths it never actually wrote". Discovered by Layer 1+2
# integration test (Qwen + Task(output_pydantic=Spec): 0/5 trials called
# verify_outputs, 0/5 actually wrote files in Scenario B). Without this
# check, framework-coerced Spec silently lies.


def test_check_claimed_paths_on_disk_all_present(tmp_path):
    from services.workflow_svc import _check_claimed_paths_on_disk
    (tmp_path / "Assets" / "Scripts").mkdir(parents=True)
    (tmp_path / "Assets" / "Scripts" / "A.cs").write_text("class A {}")
    (tmp_path / "Assets" / "Scripts" / "B.cs").write_text("class B {}")
    missing, zero_byte = _check_claimed_paths_on_disk(
        ["Assets/Scripts/A.cs", "Assets/Scripts/B.cs"], str(tmp_path),
    )
    assert missing == []
    assert zero_byte == []


def test_check_claimed_paths_on_disk_catches_missing(tmp_path):
    from services.workflow_svc import _check_claimed_paths_on_disk
    # Agent claims two files; only one exists.
    (tmp_path / "Assets").mkdir()
    (tmp_path / "Assets" / "A.cs").write_text("class A {}")
    missing, zero_byte = _check_claimed_paths_on_disk(
        ["Assets/A.cs", "Assets/Bogus.cs"], str(tmp_path),
    )
    assert missing == ["Assets/Bogus.cs"]
    assert zero_byte == []


def test_check_claimed_paths_on_disk_catches_zero_byte(tmp_path):
    """Zero-byte files are almost always failed writes — they should
    surface as zero_byte, not pass silently."""
    from services.workflow_svc import _check_claimed_paths_on_disk
    (tmp_path / "Stub.cs").write_text("")
    missing, zero_byte = _check_claimed_paths_on_disk(
        ["Stub.cs"], str(tmp_path),
    )
    assert missing == []
    assert zero_byte == ["Stub.cs"]


def test_check_claimed_paths_on_disk_refuses_path_escape(tmp_path):
    """An agent that puts `../../etc/passwd` in file_paths must NOT
    pass — even if that file happens to exist, it's outside the
    project root and not a valid contract output."""
    from services.workflow_svc import _check_claimed_paths_on_disk
    missing, zero_byte = _check_claimed_paths_on_disk(
        ["../../somewhere/else.cs"], str(tmp_path),
    )
    assert missing == ["../../somewhere/else.cs"]


def test_check_claimed_paths_on_disk_empty_input(tmp_path):
    from services.workflow_svc import _check_claimed_paths_on_disk
    missing, zero_byte = _check_claimed_paths_on_disk([], str(tmp_path))
    assert missing == []
    assert zero_byte == []


def test_check_claimed_paths_on_disk_none_project_root_skips():
    """No project root = nothing to anchor against; return empty
    (let the next defence layer surface the issue)."""
    from services.workflow_svc import _check_claimed_paths_on_disk
    missing, zero_byte = _check_claimed_paths_on_disk(
        ["Assets/A.cs"], None,
    )
    assert missing == []
    assert zero_byte == []


def test_check_claimed_paths_on_disk_skips_blank_entries(tmp_path):
    """Blank / whitespace-only entries don't get counted as missing —
    they're just no-ops. Lets a legitimately-empty file_paths slip
    through without false-positives."""
    from services.workflow_svc import _check_claimed_paths_on_disk
    missing, zero_byte = _check_claimed_paths_on_disk(
        ["", "   ", None], str(tmp_path),  # type: ignore[list-item]
    )
    assert missing == []
    assert zero_byte == []


@pytest.mark.asyncio
async def test_run_crew_rescues_executor_via_disk_when_no_emit(
    crew_env, monkeypatch, tmp_path,
):
    """Unity Developer pattern: agent wrote the .cs file via Unity MCP
    (an earlier ReAct turn) but never called emit_output. captured is
    None on the captured side, but disk shows the contract's files
    exist + non-empty. The chain should rescue this instead of halting."""
    # Sit the .cs file on disk so the rescue can find it.
    workspace = tmp_path / "workspace"
    (workspace / "Assets" / "Scripts").mkdir(parents=True)
    (workspace / "Assets" / "Scripts" / "Foo.cs").write_text(
        "using UnityEngine;\npublic class Foo : MonoBehaviour {}\n"
    )

    # Patch task row so its output_paths point at our file.
    task_row = await crew_env.get_by_id("tasks", "tk1")
    task_row["output_paths"] = json.dumps(["Assets/Scripts/Foo.cs"])

    project = await crew_env.get_by_id("projects", "p1")
    project["root_path"] = str(workspace)

    async def fake_run_step(**kwargs):
        # Executor step returns empty captured (agent didn't emit_output)
        # but the file was "created" in setup above to simulate Unity
        # MCP create_script having written it on an earlier turn.
        if kwargs["step_role"] == "executor":
            return ("Action: find_in_file\nAction Input: {...}", None)
        return ("raw", {"verdict": "pass"})

    monkeypatch.setattr(
        "services.crewai_runner.run_crew_step_with_crewai", fake_run_step)
    async def fake_resolve(_self, _agent): return "prov", "deepseek-flash"
    monkeypatch.setattr(WorkflowService, "_resolve_agent_llm", fake_resolve)
    async def fake_bcast(*a, **kw): pass
    monkeypatch.setattr(WorkflowService, "_broadcast_sub_step", fake_bcast)

    svc = WorkflowService()
    task_input = TaskInput(
        task_id="tk1", title="T1", detail="",
        agent_id="", output_schema={},
        upstream_outputs={},
        output_paths=["Assets/Scripts/Foo.cs"],  # so _extract_output_paths returns this
    )
    # Don't expect a RuntimeError — the rescue should kick in
    summary = await svc._run_crew("p1", "tk1", task_input, "crewX")
    # If we got here without raising, rescue worked. Cross-check
    # captured ended up under pop_output.
    final = pop_output("tk1")
    assert final is not None
