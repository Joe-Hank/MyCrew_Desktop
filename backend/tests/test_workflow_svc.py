"""Tests for WorkflowService — orchestration with mocked dependencies."""
import json
from unittest.mock import patch, AsyncMock

import pytest

from domain.harness.states import ProjectState, TaskState
from domain.events import ProjectStarted, TaskStarted
from services.workflow_svc import WorkflowService
from tests.conftest import FakeCRUD, FakeEventBus, FakeLlmGateway, make_task, make_project


@pytest.fixture
def env():
    """Set up a WorkflowService with all dependencies mocked."""
    crud = FakeCRUD()
    bus = FakeEventBus()
    llm = FakeLlmGateway(default_response='{"result": "done"}')

    svc = WorkflowService()

    crud.seed("projects", [make_project("proj_1")])
    crud.seed("tasks", [
        make_task("t1", deps=[], project_id="proj_1"),
        make_task("t2", deps=["t1"], project_id="proj_1"),
    ])
    crud.seed("agents", [{"id": "agent_1", "role": "coder", "goal": "code", "llm_id": "prov1:gpt-4"}])
    crud.seed("llm_providers", [{"id": "prov1", "name": "OpenAI", "kind": "openai", "base_url": "", "api_key": "sk-test"}])
    crud.seed("llm_models", [{"id": "m1", "provider_id": "prov1", "model_name": "gpt-4"}])

    return {"svc": svc, "crud": crud, "bus": bus, "llm": llm}


def _patch_deps(env):
    """Context manager to patch module-level singletons."""
    return (
        patch("services.workflow_svc.crud", env["crud"]),
        patch("services.workflow_svc.event_bus", env["bus"]),
        patch("services.workflow_svc.llm_gateway", env["llm"]),
    )


class TestWorkflowStart:
    async def test_start_success(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            await svc.start("proj_1")

            assert "proj_1" in svc.get_active_projects()
            proj = await env["crud"].get_by_id("projects", "proj_1")
            assert proj["state"] == ProjectState.RUNNING

            started_events = env["bus"].get_events_of_type(ProjectStarted)
            assert len(started_events) == 1
        finally:
            for p in patches:
                p.stop()

    async def test_start_project_not_found(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            with pytest.raises(KeyError, match="not found"):
                await svc.start("nonexistent")
        finally:
            for p in patches:
                p.stop()

    async def test_start_no_tasks(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            env["crud"].seed("projects", [make_project("proj_empty")])
            with pytest.raises(ValueError, match="no tasks"):
                await env["svc"].start("proj_empty")
        finally:
            for p in patches:
                p.stop()

    async def test_start_invalid_dag(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            env["crud"].seed("projects", [make_project("proj_cycle")])
            env["crud"].seed("tasks", [
                make_task("c1", deps=["c2"], project_id="proj_cycle"),
                make_task("c2", deps=["c1"], project_id="proj_cycle"),
            ])
            with pytest.raises(ValueError, match="DAG"):
                await env["svc"].start("proj_cycle")
        finally:
            for p in patches:
                p.stop()

    async def test_start_rejects_when_performer_missing(self, env):
        """Both channels empty → reject (was the only behaviour pre-PM v4)."""
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            env["crud"].seed("projects", [make_project("proj_no_perf")])
            env["crud"].seed("tasks", [
                {**make_task("np1", deps=[], project_id="proj_no_perf"),
                 "agent_id": None,
                 "performer_kind": None,
                 "performer_id": None},
            ])
            with pytest.raises(ValueError, match="未指定执行者"):
                await env["svc"].start("proj_no_perf")
        finally:
            for p in patches:
                p.stop()

    async def test_start_accepts_crew_performer_without_agent_id(self, env):
        """PM v4 Crew tasks have agent_id=NULL by design — start() must
        not reject them. Regression: the pre-flight used to be
        `if not t.get("agent_id")` which excluded every Crew row."""
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            env["crud"].seed("projects", [make_project("proj_crew")])
            env["crud"].seed("tasks", [
                {**make_task("ct1", deps=[], project_id="proj_crew"),
                 "agent_id": None,
                 "performer_kind": "crew",
                 "performer_id": "crew_abc"},
            ])
            # Stub _dispatch so the test doesn't actually try to load
            # the crew row — we only care that start() accepts the task.
            with patch.object(env["svc"], "_schedule_ready_tasks"):
                await env["svc"].start("proj_crew")
            assert "proj_crew" in env["svc"].get_active_projects()
        finally:
            for p in patches:
                p.stop()


class TestRetryAutoResume:
    """retry_task on a project whose harness was lost (backend restart)
    must rebuild the harness from DB instead of 404-ing. Reported
    2026-05-16 after the 「祖玛」 task wouldn't restart post-bug-fix
    deploy."""

    async def test_retry_after_orphan_rebuilds_harness(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            # Project is in the DB but NOT in svc._active — exactly the
            # state after a backend restart.
            env["crud"].seed("projects", [
                make_project("proj_orphan", state="stalled"),
            ])
            env["crud"].seed("tasks", [
                {**make_task("o1", deps=[], project_id="proj_orphan"),
                 "status": "failed", "agent_id": "agent_1"},
            ])
            assert "proj_orphan" not in svc._active

            # Stub the actual dispatch — we only care that retry no
            # longer raises and that the harness is rebuilt.
            with patch.object(svc, "_schedule_task"):
                await svc.retry_task(
                    "proj_orphan", "o1", cleanup_artifacts=False,
                )

            assert "proj_orphan" in svc._active
            proj = await env["crud"].get_by_id("projects", "proj_orphan")
            assert proj["state"] == "running"
        finally:
            for p in patches:
                p.stop()

    async def test_retry_missing_project_still_raises(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            with pytest.raises(KeyError, match="not found"):
                await svc.retry_task(
                    "proj_nonexistent", "x", cleanup_artifacts=False,
                )
        finally:
            for p in patches:
                p.stop()


class TestWorkflowPauseResume:
    async def test_pause_active_project(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            await svc.start("proj_1")
            await svc.pause("proj_1")

            proj = await env["crud"].get_by_id("projects", "proj_1")
            assert proj["state"] == ProjectState.PAUSED
        finally:
            for p in patches:
                p.stop()

    async def test_pause_inactive_raises(self, env):
        # workflow_svc.pause now has a two-tier behaviour:
        # 1. live harness present → pause it
        # 2. no harness, DB row exists → orphan reconcile (mark tasks paused)
        # 3. no harness, no DB row → raise KeyError(project_id)
        # This test exercises path 3, so the project must NOT be seeded.
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            with pytest.raises(KeyError, match="proj_does_not_exist"):
                await env["svc"].pause("proj_does_not_exist")
        finally:
            for p in patches:
                p.stop()

    async def test_resume_paused_project(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            await svc.start("proj_1")
            await svc.pause("proj_1")
            await svc.resume("proj_1")

            proj = await env["crud"].get_by_id("projects", "proj_1")
            assert proj["state"] == ProjectState.RUNNING
        finally:
            for p in patches:
                p.stop()


class TestWorkflowAbort:
    async def test_abort_cleans_up(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            await svc.start("proj_1")
            await svc.abort("proj_1", "cancelled")

            assert "proj_1" not in svc.get_active_projects()
            proj = await env["crud"].get_by_id("projects", "proj_1")
            assert proj["state"] == ProjectState.ABORTED
        finally:
            for p in patches:
                p.stop()


class TestWorkflowPauseAll:
    async def test_pause_all(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            await svc.start("proj_1")
            count = await svc.pause_all()
            assert count == 1
        finally:
            for p in patches:
                p.stop()


class TestResolveAgentLlm:
    async def test_resolve_with_colon_format(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            agent = {"llm_id": "prov1:gpt-4"}
            pid, model = await svc._resolve_agent_llm(agent)
            assert pid == "prov1"
            assert model == "gpt-4"
        finally:
            for p in patches:
                p.stop()

    async def test_resolve_provider_only(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            agent = {"llm_id": "prov1"}
            pid, model = await svc._resolve_agent_llm(agent)
            assert pid == "prov1"
            assert model == "gpt-4"
        finally:
            for p in patches:
                p.stop()

    async def test_resolve_no_agent_uses_fallback(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            pid, model = await svc._resolve_agent_llm(None)
            assert pid == "prov1"
            assert model == "gpt-4"
        finally:
            for p in patches:
                p.stop()

    async def test_resolve_no_providers_raises(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            env["crud"]._tables["llm_providers"].clear()
            env["crud"]._tables["llm_models"].clear()
            env["crud"]._tables["app_settings"].clear()
            svc = env["svc"]
            with pytest.raises(ValueError, match="未配置"):
                await svc._resolve_agent_llm(None)
        finally:
            for p in patches:
                p.stop()


class TestExtractStructuredOutput:
    async def test_direct_json_parse(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            result = await svc._extract_structured_output(
                "proj_1", "t1", '{"name": "test"}', {"type": "object"})
            assert result == {"name": "test"}
        finally:
            for p in patches:
                p.stop()

    async def test_markdown_json_extraction(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            text = 'Here is the result:\n```json\n{"name": "test"}\n```\nDone.'
            result = await svc._extract_structured_output(
                "proj_1", "t1", text, {"type": "object"})
            assert result == {"name": "test"}
        finally:
            for p in patches:
                p.stop()

    async def test_llm_fallback_extraction(self, env):
        env["llm"].default_response = '{"extracted": true}'
        env["crud"].seed("tasks", [
            make_task("t1", project_id="proj_1"),
        ])
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            result = await svc._extract_structured_output(
                "proj_1", "t1", "some unstructured text", {"type": "object"})
            assert result == {"extracted": True}
            assert len(env["llm"].call_log) == 1
        finally:
            for p in patches:
                p.stop()

    async def test_total_failure_wraps_raw(self, env):
        env["llm"].default_response = "not json"
        env["crud"].seed("tasks", [
            make_task("t1", project_id="proj_1"),
        ])
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            result = await svc._extract_structured_output(
                "proj_1", "t1", "raw text", {"type": "object"})
            assert result == {"_raw": "raw text"}
        finally:
            for p in patches:
                p.stop()


class TestLoadTasks:
    async def test_deserializes_json_fields(self, env):
        patches = _patch_deps(env)
        for p in patches:
            p.start()
        try:
            svc = env["svc"]
            tasks = await svc._load_tasks("proj_1")
            assert len(tasks) == 2
            for t in tasks:
                assert isinstance(t["deps"], list)
                assert isinstance(t["output_schema"], dict)
        finally:
            for p in patches:
                p.stop()
