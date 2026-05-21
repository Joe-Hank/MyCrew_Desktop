"""Crew v5 fan-out — merge + scheduler-filter + (async) fan-out dispatch.

Doesn't try to spin up real CrewAI; instead exercises the three pure-ish
seams:
  1. orchestrator._merge_into_crew_groups — pure function, cluster rule
  2. state_machine.get_ready_tasks — skip children
  3. workflow_svc._fanout_step — mock the per-child kickoff, verify
     gather + semaphore + result aggregation + status flips
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from agents.sub_agents._planner_orchestrator import (
    _longest_common_prefix,
    _merge_into_crew_groups,
)
from domain.harness.state_machine import HarnessStateMachine
from domain.harness.states import ProjectState


# ── _merge_into_crew_groups ─────────────────────────────────────────


def test_merge_groups_homogeneous_sprites():
    """5 sprite tasks with same crew_id + same deps → 1 parent + 5 children."""
    pathed = [
        {"title": "setup", "kind": "setup", "deps": [], "output_paths": []},
        {"title": "Butcher sprite", "kind": "regular", "deps": [0],
         "output_paths": ["Assets/Sprites/Butcher.png"]},
        {"title": "Hughie sprite", "kind": "regular", "deps": [0],
         "output_paths": ["Assets/Sprites/Hughie.png"]},
        {"title": "Homelander sprite", "kind": "regular", "deps": [0],
         "output_paths": ["Assets/Sprites/Homelander.png"]},
        {"title": "scene", "kind": "regular", "deps": [0, 1, 2, 3],
         "output_paths": ["Assets/Scenes/Main.unity"]},
    ]
    assignments = [
        {"task_index": 1, "performer_ref": {"kind": "crew", "id": "crew_art"}, "reason": ""},
        {"task_index": 2, "performer_ref": {"kind": "crew", "id": "crew_art"}, "reason": ""},
        {"task_index": 3, "performer_ref": {"kind": "crew", "id": "crew_art"}, "reason": ""},
        {"task_index": 4, "performer_ref": {"kind": "crew", "id": "crew_scene"}, "reason": ""},
    ]
    new_tasks, new_assigns = _merge_into_crew_groups(pathed, assignments)

    # Parent appended at index 5
    assert len(new_tasks) == 6
    parent = new_tasks[5]
    assert parent["kind"] == "crew"
    assert parent["performer_id"] == "crew_art"
    assert parent["deps"] == [0]
    # Union of children's output_paths
    assert set(parent["output_paths"]) == {
        "Assets/Sprites/Butcher.png",
        "Assets/Sprites/Hughie.png",
        "Assets/Sprites/Homelander.png",
    }

    # Children point at parent + deps rewritten
    for i in (1, 2, 3):
        assert new_tasks[i]["parent_task_id"] == 5
        assert new_tasks[i]["deps"] == [5]

    # Downstream task's deps rewritten: 1,2,3 → 5 (deduped)
    assert new_tasks[4]["deps"] == [0, 5]

    # New parent assignment exists
    parent_assigns = [a for a in new_assigns if a["task_index"] == 5]
    assert len(parent_assigns) == 1
    assert parent_assigns[0]["performer_ref"] == {"kind": "crew", "id": "crew_art"}


def test_merge_groups_singleton_not_merged():
    """A crew task with no siblings stays alone — no parent created."""
    pathed = [
        {"title": "setup", "kind": "setup", "deps": [], "output_paths": []},
        {"title": "single Unity script", "kind": "regular", "deps": [0],
         "output_paths": ["Assets/Scripts/Foo.cs"]},
    ]
    assignments = [
        {"task_index": 1, "performer_ref": {"kind": "crew", "id": "crew_sys"}, "reason": ""},
    ]
    new_tasks, _ = _merge_into_crew_groups(pathed, assignments)
    assert new_tasks is pathed or len(new_tasks) == len(pathed)
    assert "parent_task_id" not in new_tasks[1]


def test_merge_groups_skips_setup_and_final_qa():
    """setup / final_qa are never grouped even when assigned to same crew."""
    pathed = [
        {"title": "setup", "kind": "setup", "deps": [], "output_paths": []},
        {"title": "setup2", "kind": "setup", "deps": [], "output_paths": []},
        {"title": "qa1", "kind": "final_qa", "deps": [0], "output_paths": []},
        {"title": "qa2", "kind": "final_qa", "deps": [0], "output_paths": []},
    ]
    assignments = [
        {"task_index": 0, "performer_ref": {"kind": "crew", "id": "c1"}, "reason": ""},
        {"task_index": 1, "performer_ref": {"kind": "crew", "id": "c1"}, "reason": ""},
        {"task_index": 2, "performer_ref": {"kind": "crew", "id": "c1"}, "reason": ""},
        {"task_index": 3, "performer_ref": {"kind": "crew", "id": "c1"}, "reason": ""},
    ]
    new_tasks, _ = _merge_into_crew_groups(pathed, assignments)
    # No grouping → same length, no parent appended
    assert len(new_tasks) == 4


def test_merge_groups_different_deps_not_clustered():
    """Same crew but different upstream → independent clusters."""
    pathed = [
        {"title": "setup", "kind": "setup", "deps": [], "output_paths": []},
        {"title": "head", "kind": "regular", "deps": [0], "output_paths": ["a.cs"]},
        {"title": "A1", "kind": "regular", "deps": [0, 1], "output_paths": ["x.cs"]},
        {"title": "A2", "kind": "regular", "deps": [0, 1], "output_paths": ["y.cs"]},
        {"title": "B1", "kind": "regular", "deps": [0], "output_paths": ["z.cs"]},
    ]
    assignments = [
        {"task_index": 1, "performer_ref": {"kind": "agent", "id": "a"}, "reason": ""},
        {"task_index": 2, "performer_ref": {"kind": "crew", "id": "c1"}, "reason": ""},
        {"task_index": 3, "performer_ref": {"kind": "crew", "id": "c1"}, "reason": ""},
        {"task_index": 4, "performer_ref": {"kind": "crew", "id": "c1"}, "reason": ""},
    ]
    new_tasks, new_assigns = _merge_into_crew_groups(pathed, assignments)
    # A1/A2 cluster (deps={0,1}) AND B1 alone (deps={0}). Only A1/A2 merged.
    # Result: 5 original + 1 parent = 6
    assert len(new_tasks) == 6
    parent = new_tasks[5]
    children_idxs = [
        i for i, t in enumerate(new_tasks) if t.get("parent_task_id") == 5
    ]
    assert sorted(children_idxs) == [2, 3]  # B1 (index 4) NOT a child
    assert new_tasks[4].get("parent_task_id") is None


def test_longest_common_prefix():
    assert _longest_common_prefix(["foo_bar", "foo_baz"]) == "foo_ba"
    assert _longest_common_prefix(["abc", "abc"]) == "abc"
    assert _longest_common_prefix(["abc", "xyz"]) == ""
    assert _longest_common_prefix([]) == ""


# ── state_machine.get_ready_tasks scheduler filter ──────────────────


def test_scheduler_skips_child_tasks():
    """Tasks with parent_task_id != NULL never appear in get_ready_tasks."""
    tasks = [
        {"id": "setup", "status": "done", "deps": [], "kind": "setup"},
        # parent of 3 fan-out children
        {"id": "parent", "status": "pending", "deps": ["setup"], "kind": "crew"},
        # 3 children — their deps include parent but they should be skipped
        # regardless because of parent_task_id filter
        {"id": "c1", "status": "pending", "deps": ["parent"],
         "kind": "regular", "parent_task_id": "parent"},
        {"id": "c2", "status": "pending", "deps": ["parent"],
         "kind": "regular", "parent_task_id": "parent"},
        {"id": "c3", "status": "pending", "deps": ["parent"],
         "kind": "regular", "parent_task_id": "parent"},
    ]
    h = HarnessStateMachine("p1", ProjectState.RUNNING, tasks)
    ready = [t["id"] for t in h.get_ready_tasks()]
    # Only parent should be ready — setup is already done, children
    # skipped despite NULL-parent's deps being technically clear-able.
    assert ready == ["parent"]
    assert "c1" not in ready and "c2" not in ready and "c3" not in ready


# ── _fanout_step dispatch + semaphore (async, with mocks) ───────────


@pytest.mark.asyncio
async def test_fanout_step_aggregates_results(tmp_path, monkeypatch):
    """_fanout_step should: gather all children, respect concurrency cap,
    aggregate captured into {results, count, completed, failed}.
    """
    # Set up a fake project root so _save_task_input doesn't choke
    from infra.runtime import set_main_loop
    set_main_loop(asyncio.get_running_loop())

    from services.workflow_svc import WorkflowService
    svc = WorkflowService()

    # Stub crud.get_all to return 3 fake child rows
    fake_children = [
        {"id": "c1", "title": "Child 1", "kind": "regular",
         "output_schema": "{}", "output_paths": '["a.cs"]',
         "code_contract": None, "parent_step_index": None,
         "agent_id": "agent_x"},
        {"id": "c2", "title": "Child 2", "kind": "regular",
         "output_schema": "{}", "output_paths": '["b.cs"]',
         "code_contract": None, "parent_step_index": None,
         "agent_id": "agent_x"},
        {"id": "c3", "title": "Child 3", "kind": "regular",
         "output_schema": "{}", "output_paths": '["c.cs"]',
         "code_contract": None, "parent_step_index": None,
         "agent_id": "agent_x"},
    ]

    # Track concurrent invocations to verify semaphore
    in_flight = 0
    max_in_flight = 0
    invocations: list[str] = []

    async def fake_run_step(*, parent_task_id, **kwargs):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        invocations.append(parent_task_id)
        await asyncio.sleep(0.05)  # let other tasks pile up
        in_flight -= 1
        return ("done", {"verdict": "pass", "file_paths": [f"{parent_task_id}.cs"]})

    # crud ops we need to stub
    from infra.repo import crud as _crud

    async def fake_get_all(table, where=None, args=()):
        if table == "tasks" and where == "parent_task_id = ?":
            return list(fake_children)
        return []

    update_calls: list[tuple[str, dict]] = []

    async def fake_update_by_id(table, rid, fields):
        update_calls.append((rid, dict(fields)))
        return True

    async def noop_save(*a, **kw):
        return None

    # Disable WS broadcast (no manager in test)
    async def noop_broadcast(*a, **kw):
        return None

    monkeypatch.setattr(_crud, "get_all", fake_get_all)
    monkeypatch.setattr(_crud, "update_by_id", fake_update_by_id)
    monkeypatch.setattr(svc, "_save_task_input", noop_save)
    monkeypatch.setattr(svc, "_save_task_output", noop_save)
    monkeypatch.setattr(svc, "_broadcast_parallel_progress", noop_broadcast)

    # Mock the per-child kickoff
    from services import crewai_runner
    monkeypatch.setattr(crewai_runner, "run_crew_step_with_crewai", fake_run_step)

    result = await svc._fanout_step(
        project_id="p1",
        parent_task_id="parent",
        project_root=str(tmp_path),
        step={"step_instructions": "do the thing", "fanout": {"concurrency_cap": 2}},
        step_index=1,
        step_role="executor",
        agent_row={"id": "agent_x", "role": "Unity Developer"},
        provider_id="prov_x",
        model_name="model_x",
        head_spec={"design": "spec"},
        concurrency=2,
    )

    assert result["count"] == 3
    assert result["completed"] == 3
    assert result["failed"] == 0
    assert len(result["results"]) == 3
    # All children invoked
    assert set(invocations) == {"c1", "c2", "c3"}
    # Semaphore should have kept in-flight ≤ cap=2
    assert max_in_flight <= 2, f"semaphore breach: max_in_flight={max_in_flight}"
    # Each child got marked done
    done_updates = [u for u in update_calls if u[1].get("status") == "done"]
    assert len(done_updates) == 3


@pytest.mark.asyncio
async def test_fanout_step_one_child_fails_others_continue(tmp_path, monkeypatch):
    """A single child raising should not abort siblings; the failure
    surfaces in results[k] with verdict='fail'."""
    from infra.runtime import set_main_loop
    set_main_loop(asyncio.get_running_loop())

    from services.workflow_svc import WorkflowService
    svc = WorkflowService()

    fake_children = [
        {"id": f"c{k}", "title": f"Child {k}", "kind": "regular",
         "output_schema": "{}", "output_paths": "[]",
         "code_contract": None, "parent_step_index": None,
         "agent_id": "a"}
        for k in (1, 2, 3)
    ]

    async def fake_run_step(*, parent_task_id, **kwargs):
        if parent_task_id == "c2":
            raise RuntimeError("boom for c2")
        return ("ok", {"verdict": "pass"})

    from infra.repo import crud as _crud
    async def fake_get_all(table, where=None, args=()):
        return list(fake_children) if table == "tasks" else []
    async def fake_update(*a, **kw): return True
    async def noop(*a, **kw): return None

    monkeypatch.setattr(_crud, "get_all", fake_get_all)
    monkeypatch.setattr(_crud, "update_by_id", fake_update)
    monkeypatch.setattr(svc, "_save_task_input", noop)
    monkeypatch.setattr(svc, "_save_task_output", noop)
    monkeypatch.setattr(svc, "_broadcast_parallel_progress", noop)
    from services import crewai_runner
    monkeypatch.setattr(crewai_runner, "run_crew_step_with_crewai", fake_run_step)

    result = await svc._fanout_step(
        project_id="p1",
        parent_task_id="parent",
        project_root=str(tmp_path),
        step={"step_instructions": "..."},
        step_index=1,
        step_role="executor",
        agent_row={"id": "a", "role": "Unity Developer"},
        provider_id="prov", model_name="m",
        head_spec=None,
        concurrency=3,
    )

    assert result["count"] == 3
    assert result["completed"] == 2
    assert result["failed"] == 1
    # Find c2 in results
    c2_result = next(r for r in result["results"] if r["child_task_id"] == "c2")
    assert c2_result["verdict"] == "fail"
    assert "boom for c2" in c2_result["error"]
    # c1 / c3 still pass
    for r in result["results"]:
        if r["child_task_id"] != "c2":
            assert r["verdict"] == "pass"
