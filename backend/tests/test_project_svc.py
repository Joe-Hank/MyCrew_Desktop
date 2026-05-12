"""Tests for ProjectService — CRUD, cloning, deletion cascade."""
import json
from unittest.mock import patch

import pytest

from services.project_svc import ProjectService
from tests.conftest import FakeCRUD, make_project, make_task


@pytest.fixture
def env():
    crud = FakeCRUD()
    svc = ProjectService()
    return {"svc": svc, "crud": crud}


def _patch(env):
    return patch("services.project_svc.crud", env["crud"])


class TestCreateProject:
    async def test_basic_create(self, env):
        with _patch(env):
            result = await env["svc"].create_project({"name": "My Project"})
            assert result["name"] == "My Project"
            assert result["state"] == "ready"
            assert result["id"].startswith("proj_")

    async def test_create_with_tasks(self, env):
        with _patch(env):
            tasks = [
                {"title": "Task 1", "detail": "do step 1", "deps": [], "output_schema": {}},
                {"title": "Task 2", "detail": "do step 2", "deps": [], "output_schema": {}},
            ]
            result = await env["svc"].create_project_with_tasks(
                {"name": "Project X"}, tasks)
            assert result["name"] == "Project X"
            assert len(result["tasks"]) == 2

    async def test_create_serializes_json_fields(self, env):
        with _patch(env):
            tasks = [{"title": "T1", "deps": [0], "output_schema": {"type": "object"}}]
            await env["svc"].create_project_with_tasks({"name": "P"}, tasks)
            stored = list(env["crud"]._tables["tasks"].values())
            assert isinstance(stored[0]["deps"], str)
            assert isinstance(stored[0]["output_schema"], str)


class TestGetProject:
    async def test_get_existing(self, env):
        with _patch(env):
            await env["svc"].create_project({"name": "P1"})
            proj_id = list(env["crud"]._tables["projects"].keys())[0]
            result = await env["svc"].get_project(proj_id)
            assert result is not None
            assert result["name"] == "P1"

    async def test_get_nonexistent(self, env):
        with _patch(env):
            result = await env["svc"].get_project("nonexistent")
            assert result is None


class TestListProjects:
    async def test_list_with_task_counts(self, env):
        with _patch(env):
            proj = await env["svc"].create_project({"name": "P1"})
            env["crud"].seed("tasks", [
                make_task("t1", project_id=proj["id"], status="done"),
                make_task("t2", project_id=proj["id"], status="pending"),
            ])
            result = await env["svc"].list_projects()
            item = result["items"][0]
            assert item["task_count"] == 2
            assert item["done_count"] == 1
            assert item["progress_pct"] == 50.0

    async def test_empty_list(self, env):
        with _patch(env):
            result = await env["svc"].list_projects()
            assert result["items"] == []
            assert result["total"] == 0


class TestCloneProject:
    async def test_clone_creates_copy(self, env):
        with _patch(env):
            proj = await env["svc"].create_project({"name": "Original"})
            env["crud"].seed("tasks", [
                make_task("t1", project_id=proj["id"]),
                make_task("t2", deps=["t1"], project_id=proj["id"]),
            ])
            # Re-get to include tasks
            proj = await env["svc"].get_project(proj["id"])

            clone = await env["svc"].clone_project(proj["id"])
            assert clone["name"] == "Original (副本)"
            assert clone["id"] != proj["id"]
            assert clone["state"] == "ready"
            assert len(clone["tasks"]) == 2

    async def test_clone_nonexistent_raises(self, env):
        with _patch(env):
            with pytest.raises(KeyError, match="not found"):
                await env["svc"].clone_project("nonexistent")


class TestDeleteProject:
    async def test_cascading_delete(self, env):
        with _patch(env):
            proj = await env["svc"].create_project({"name": "ToDelete"})
            env["crud"].seed("tasks", [
                make_task("t1", project_id=proj["id"]),
            ])
            session = await env["crud"].insert("inception_sessions", {
                "project_id": proj["id"], "llm_id": "test",
            }, id_prefix="incep_")
            await env["crud"].insert("inception_messages", {
                "session_id": session["id"], "role": "user", "content": "hi",
            }, id_prefix="msg_")

            await env["svc"].delete_project(proj["id"])

            assert await env["crud"].get_by_id("projects", proj["id"]) is None
            assert len(env["crud"]._tables["tasks"]) == 0
            assert len(env["crud"]._tables["inception_sessions"]) == 0
            assert len(env["crud"]._tables["inception_messages"]) == 0


class TestUpdateRootPath:
    async def test_update(self, env):
        with _patch(env):
            proj = await env["svc"].create_project({"name": "P1"})
            result = await env["svc"].update_root_path(proj["id"], "/new/path")
            assert result["root_path"] == "/new/path"


class TestDeserializeTask:
    def test_deserializes_json_strings(self):
        svc = ProjectService()
        row = {
            "id": "t1",
            "deps": '["t0"]',
            "output_schema": '{"type": "object"}',
        }
        result = svc._deserialize_task(row)
        assert result["deps"] == ["t0"]
        assert result["output_schema"] == {"type": "object"}

    def test_handles_invalid_json(self):
        svc = ProjectService()
        row = {"id": "t1", "deps": "invalid", "output_schema": "bad"}
        result = svc._deserialize_task(row)
        assert result["deps"] == []
        assert result["output_schema"] == {}

    def test_already_parsed(self):
        svc = ProjectService()
        row = {"id": "t1", "deps": ["t0"], "output_schema": {}}
        result = svc._deserialize_task(row)
        assert result["deps"] == ["t0"]
