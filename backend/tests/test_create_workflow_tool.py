"""Tests for the CreateWorkflowTool — Plan Maker's primary action.

We bypass the asyncio bridge entirely in tests by monkey-patching
`GuardedLocalTool._guarded_local` to invoke the coroutine factory via
`asyncio.run()`. The bridge itself is exercised indirectly elsewhere.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.tools.builtin.local.create_workflow import (
    CreateWorkflowTool,
    _normalize_tasks,
    make_create_workflow_tool,
)
from tests.conftest import FakeCRUD, FakeWSManager


def _direct_guarded_local(self, coro_factory):
    """Replacement for GuardedLocalTool._guarded_local in tests.

    Runs the coroutine returned by `coro_factory()` in a fresh event
    loop on this thread — no main-loop hop, no threading. Permission
    checks are still enforced (they live inside the factory's wrapper
    in real code; here we just skip them for simplicity).
    """
    return asyncio.run(coro_factory())


@pytest.fixture
def env():
    crud = FakeCRUD()
    ws = FakeWSManager()
    crud.seed("inception_sessions", [
        {"id": "incep_test", "project_id": None, "llm_id": "prov_x:m"},
    ])
    return {"crud": crud, "ws": ws}


@pytest.fixture
def patched_tool(env):
    """Yield a context where create_workflow has all I/O hooked to fakes."""
    with patch("infra.repo.crud.insert", env["crud"].insert), \
         patch("infra.repo.crud.get_by_id", env["crud"].get_by_id), \
         patch("infra.repo.crud.get_all", env["crud"].get_all), \
         patch("infra.repo.crud.update_by_id", env["crud"].update_by_id), \
         patch("infra.repo.crud.delete_by_id", env["crud"].delete_by_id), \
         patch("infra.repo.crud.count", env["crud"].count), \
         patch("infra.repo.crud.paginate", env["crud"].paginate), \
         patch("api.ws.manager", env["ws"]), \
         patch("src.tools.builtin._base.GuardedLocalTool._guarded_local",
               _direct_guarded_local):
        yield


# ── _normalize_tasks ─────────────────────────────────────────────

class TestNormalize:
    def test_final_qa_present_unchanged(self):
        tasks = [
            {"title": "t1", "deps": [], "kind": "regular"},
            {"title": "qa", "deps": [0], "kind": "final_qa"},
        ]
        out = _normalize_tasks(tasks)
        assert len(out) == 2
        assert sum(1 for t in out if t.get("kind") == "final_qa") == 1

    def test_final_qa_auto_appended_with_terminal_deps(self):
        tasks = [
            {"title": "t1", "deps": []},
            {"title": "t2", "deps": []},
        ]
        out = _normalize_tasks(tasks)
        assert len(out) == 3
        qa = out[-1]
        assert qa["kind"] == "final_qa"
        assert set(qa["deps"]) == {0, 1}
        for f in ("verdict", "overall_score", "issues", "summary"):
            assert f in qa["output_schema"]["properties"]


# ── _run() behaviour with patched I/O ────────────────────────────

class TestRun:
    def test_persists_project_and_tasks(self, env, patched_tool):
        tool = make_create_workflow_tool("incep_test")
        result = tool._run(
            name="Test Project",
            execution_kind="sequential",
            tasks=[
                {"title": "Step A", "detail": "do A", "deps": []},
                {"title": "Step B", "detail": "do B", "deps": [0]},
            ],
        )
        assert isinstance(result, str)
        assert "Workflow created" in result
        assert len(env["crud"]._tables["projects"]) == 1
        assert len(env["crud"]._tables["tasks"]) == 3  # 2 user + 1 final_qa

    def test_session_bound_to_project(self, env, patched_tool):
        tool = make_create_workflow_tool("incep_test")
        tool._run(name="P", execution_kind="sequential",
                  tasks=[{"title": "x", "deps": []}])
        sess = env["crud"]._tables["inception_sessions"]["incep_test"]
        assert sess.get("project_id") is not None

    def test_workflow_created_event_broadcast(self, env, patched_tool):
        tool = make_create_workflow_tool("incep_test")
        tool._run(name="P", execution_kind="sequential",
                  tasks=[{"title": "x", "deps": []}])
        events = [b for b in env["ws"].broadcasts if b[0] == "inception.workflow_created"]
        assert len(events) == 1
        payload = events[0][1]
        assert payload["session_id"] == "incep_test"
        assert payload["project_id"]
        assert payload["blueprint"]["name"] == "P"

    def test_invalid_execution_kind(self, env, patched_tool):
        tool = make_create_workflow_tool("incep_test")
        result = tool._run(name="P", execution_kind="banana",
                           tasks=[{"title": "x", "deps": []}])
        assert "[Error]" in result
        assert "invalid execution_kind" in result.lower()
        assert len(env["crud"]._tables["projects"]) == 0

    def test_empty_tasks_rejected(self, env, patched_tool):
        tool = make_create_workflow_tool("incep_test")
        result = tool._run(name="P", execution_kind="sequential", tasks=[])
        assert "[Error]" in result

    def test_duplicate_call_protection(self, env, patched_tool):
        env["crud"]._tables["inception_sessions"]["incep_test"]["project_id"] = "proj_existing"
        tool = make_create_workflow_tool("incep_test")
        result = tool._run(name="P", execution_kind="sequential",
                           tasks=[{"title": "x", "deps": []}])
        assert "[Error]" in result
        assert "already" in result.lower()
        assert len(env["crud"]._tables["projects"]) == 0

    def test_missing_session_id_raw_instantiation(self):
        """Without factory binding, the tool refuses up-front (no I/O needed)."""
        raw = CreateWorkflowTool()
        result = raw._run(name="P", execution_kind="sequential",
                          tasks=[{"title": "x"}])
        assert "[Error]" in result
        assert "session_id" in result


# ── Factory binding ──────────────────────────────────────────────

class TestFactory:
    def test_factory_binds_unique_session(self):
        a = make_create_workflow_tool("incep_a")
        b = make_create_workflow_tool("incep_b")
        assert a._bound_session_id == "incep_a"
        assert b._bound_session_id == "incep_b"
        assert a.name == b.name == "create_workflow"

    def test_args_schema_excludes_session_id(self):
        tool = make_create_workflow_tool("incep_x")
        fields = list(tool.args_schema.model_fields.keys())
        assert "session_id" not in fields
        assert "name" in fields
        assert "execution_kind" in fields
        assert "tasks" in fields
