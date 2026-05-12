"""Tests for InceptionService — session management, LLM calls, blueprint parsing."""
import json
from unittest.mock import patch, AsyncMock

import pytest

from services.inception_svc import InceptionService, SYSTEM_PROMPT
from tests.conftest import FakeCRUD, FakeLlmGateway, FakeWSManager


@pytest.fixture
def env():
    crud = FakeCRUD()
    llm = FakeLlmGateway()
    ws = FakeWSManager()
    svc = InceptionService()
    return {"svc": svc, "crud": crud, "llm": llm, "ws": ws}


def _patch(env):
    return (
        patch("services.inception_svc.crud", env["crud"]),
        patch("services.inception_svc.llm_gateway", env["llm"]),
        patch("services.inception_svc.manager", env["ws"]),
    )


class TestCreateSession:
    async def test_creates_session(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            session = await env["svc"].create_session("prov1:gpt-4")
            assert session["llm_id"] == "prov1:gpt-4"
            assert session["id"].startswith("incep_")
        finally:
            for p in patches:
                p.stop()

    async def test_thinking_mode(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            session = await env["svc"].create_session("prov1:gpt-4", thinking_mode=True)
            assert session["thinking_mode"] == 1
        finally:
            for p in patches:
                p.stop()


class TestSendMessage:
    async def test_send_and_receive(self, env):
        env["llm"].default_response = "I'll help you plan this project."
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            session = await env["svc"].create_session("prov1:gpt-4")
            result = await env["svc"].send_message(session["id"], "Build a website")

            assert result["user_message"]["content"] == "Build a website"
            assert result["ai_message"]["content"] == "I'll help you plan this project."
            assert result["blueprint"] is None

            broadcasts = [b for b in env["ws"].broadcasts if b[0] == "inception.message"]
            assert len(broadcasts) == 2
        finally:
            for p in patches:
                p.stop()

    async def test_send_extracts_blueprint(self, env):
        blueprint = {
            "name": "Website",
            "execution_kind": "sequential",
            "tasks": [{"title": "Design", "detail": "UI design", "deps": [], "output_schema": {}, "kind": "regular"}]
        }
        env["llm"].default_response = f"Here's the plan:\n```json\n{json.dumps(blueprint)}\n```"
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            session = await env["svc"].create_session("prov1:gpt-4")
            result = await env["svc"].send_message(session["id"], "Build it")

            assert result["blueprint"] is not None
            assert result["blueprint"]["name"] == "Website"

            drafted = [b for b in env["ws"].broadcasts if b[0] == "inception.tasks_drafted"]
            assert len(drafted) == 1
        finally:
            for p in patches:
                p.stop()

    async def test_send_session_not_found(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            with pytest.raises(KeyError, match="not found"):
                await env["svc"].send_message("fake_id", "hello")
        finally:
            for p in patches:
                p.stop()


class TestIndexPath:
    async def test_add_path(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            session = await env["svc"].create_session("prov1:gpt-4")
            result = await env["svc"].index_path(session["id"], "/src/main.py")
            assert "/src/main.py" in result["indexed_paths"]
        finally:
            for p in patches:
                p.stop()

    async def test_no_duplicate_paths(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            session = await env["svc"].create_session("prov1:gpt-4")
            await env["svc"].index_path(session["id"], "/src/main.py")
            result = await env["svc"].index_path(session["id"], "/src/main.py")
            assert result["indexed_paths"].count("/src/main.py") == 1
        finally:
            for p in patches:
                p.stop()

    async def test_session_not_found(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            with pytest.raises(KeyError):
                await env["svc"].index_path("nonexistent", "/path")
        finally:
            for p in patches:
                p.stop()


class TestFinalize:
    async def test_finalize_with_blueprint(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            session = await env["svc"].create_session("prov1:gpt-4")
            blueprint = {
                "name": "Test Project",
                "execution_kind": "sequential",
                "tasks": [
                    {"title": "Step 1", "detail": "do it", "deps": [], "output_schema": {}, "kind": "regular"},
                ],
            }
            mock_psvc = AsyncMock()
            mock_psvc.create_project_with_tasks = AsyncMock(return_value={
                "id": "proj_new", "name": "Test Project", "tasks": [],
            })
            with patch.dict("sys.modules", {}):
                import services.inception_svc as mod
                orig = None
                # finalize does a deferred import: from services.project_svc import project_svc
                # We patch the module's project_svc at call time
                with patch("services.project_svc.project_svc", mock_psvc):
                    result = await env["svc"].finalize(session["id"], blueprint)
                    assert result["id"] == "proj_new"

                    call_args = mock_psvc.create_project_with_tasks.call_args
                    tasks_arg = call_args.kwargs.get("tasks", call_args[0][1] if len(call_args[0]) > 1 else [])
                    has_qa = any(t.get("kind") == "final_qa" for t in tasks_arg)
                    assert has_qa
        finally:
            for p in patches:
                p.stop()

    async def test_finalize_no_blueprint_raises(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            session = await env["svc"].create_session("prov1:gpt-4")
            with pytest.raises(ValueError, match="No valid"):
                await env["svc"].finalize(session["id"])
        finally:
            for p in patches:
                p.stop()

    async def test_finalize_session_not_found(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            with pytest.raises(KeyError):
                await env["svc"].finalize("nonexistent")
        finally:
            for p in patches:
                p.stop()


class TestBlueprintParsing:
    def test_valid_blueprint(self):
        svc = InceptionService()
        text = '```json\n{"name": "P", "tasks": [{"title": "T1"}]}\n```'
        result = svc._try_parse_blueprint(text)
        assert result is not None
        assert result["name"] == "P"

    def test_no_json_block(self):
        svc = InceptionService()
        assert svc._try_parse_blueprint("no json here") is None

    def test_json_without_tasks(self):
        svc = InceptionService()
        text = '```json\n{"name": "P"}\n```'
        assert svc._try_parse_blueprint(text) is None

    def test_invalid_json(self):
        svc = InceptionService()
        text = '```json\n{invalid}\n```'
        assert svc._try_parse_blueprint(text) is None

    def test_json_array_ignored(self):
        svc = InceptionService()
        text = '```json\n[1, 2, 3]\n```'
        assert svc._try_parse_blueprint(text) is None


class TestResolveLlm:
    async def test_colon_format(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            pid, model = await env["svc"]._resolve_llm("prov1:gpt-4")
            assert pid == "prov1"
            assert model == "gpt-4"
        finally:
            for p in patches:
                p.stop()

    async def test_provider_only(self, env):
        env["crud"].seed("llm_models", [{"id": "m1", "provider_id": "prov1", "model_name": "gpt-4o"}])
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            pid, model = await env["svc"]._resolve_llm("prov1")
            assert pid == "prov1"
            assert model == "gpt-4o"
        finally:
            for p in patches:
                p.stop()

    async def test_empty_llm_id_uses_default(self, env):
        env["crud"].seed("app_settings", [{"id": "s1", "key": "default_inception_model", "value": "prov1:gpt-4"}])
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            pid, model = await env["svc"]._resolve_llm("")
            assert pid == "prov1"
            assert model == "gpt-4"
        finally:
            for p in patches:
                p.stop()

    async def test_no_config_raises(self, env):
        patches = _patch(env)
        for p in patches:
            p.start()
        try:
            with pytest.raises(ValueError, match="未配置"):
                await env["svc"]._resolve_llm("")
        finally:
            for p in patches:
                p.stop()
