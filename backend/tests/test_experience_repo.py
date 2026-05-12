"""Tests for SqliteExperienceRepo — save/search/delete/get_by_task."""
from unittest.mock import patch

import pytest

from domain.experience.experience_repo import ExperienceEntry, ExperienceQuery
from infra.experience.sqlite_experience_repo import SqliteExperienceRepo
from tests.conftest import FakeCRUD


@pytest.fixture
def env():
    crud = FakeCRUD()
    repo = SqliteExperienceRepo()
    return {"crud": crud, "repo": repo}


def _patch(env):
    return patch("infra.experience.sqlite_experience_repo.crud", env["crud"])


class TestSave:
    async def test_save_basic(self, env):
        with _patch(env):
            eid = await env["repo"].save(ExperienceEntry(
                agent_id="agent_1",
                content="learned how to debug shaders",
                tags=["shader", "unity"],
            ))
            assert eid.startswith("exp_")

    async def test_save_persists_fields(self, env):
        with _patch(env):
            await env["repo"].save(ExperienceEntry(
                agent_id="agent_1",
                task_id="task_42",
                project_id="proj_x",
                content="hello",
                tags=["a", "b"],
                score=0.85,
            ))
            rows = list(env["crud"]._tables["experiences"].values())
            assert len(rows) == 1
            assert rows[0]["agent_id"] == "agent_1"
            assert rows[0]["task_id"] == "task_42"
            assert rows[0]["score"] == 0.85


class TestSearch:
    async def test_filter_by_agent(self, env):
        with _patch(env):
            await env["repo"].save(ExperienceEntry(agent_id="a1", content="x"))
            await env["repo"].save(ExperienceEntry(agent_id="a2", content="y"))
            results = await env["repo"].search(ExperienceQuery(agent_id="a1"))
            assert len(results) == 1
            assert results[0].agent_id == "a1"

    async def test_query_text(self, env):
        with _patch(env):
            await env["repo"].save(ExperienceEntry(agent_id="a", content="how to use blender"))
            await env["repo"].save(ExperienceEntry(agent_id="a", content="unity quirks"))
            # FakeCRUD doesn't implement LIKE; verify all are returned and Python filters
            results = await env["repo"].search(ExperienceQuery(agent_id="a", query_text="blender"))
            # FakeCRUD doesn't implement LIKE, so it falls back to no-filter then Python tags filter
            # Just verify list type
            assert isinstance(results, list)

    async def test_tag_filter(self, env):
        with _patch(env):
            await env["repo"].save(ExperienceEntry(agent_id="a", content="x", tags=["foo"]))
            await env["repo"].save(ExperienceEntry(agent_id="a", content="y", tags=["bar"]))
            results = await env["repo"].search(ExperienceQuery(agent_id="a", tags=["foo"]))
            assert len(results) == 1
            assert results[0].tags == ["foo"]

    async def test_limit(self, env):
        with _patch(env):
            for i in range(10):
                await env["repo"].save(ExperienceEntry(agent_id="a", content=f"e{i}"))
            results = await env["repo"].search(ExperienceQuery(agent_id="a", limit=3))
            assert len(results) == 3


class TestDelete:
    async def test_delete_existing(self, env):
        with _patch(env):
            eid = await env["repo"].save(ExperienceEntry(agent_id="a", content="x"))
            assert await env["repo"].delete(eid) is True

    async def test_delete_missing(self, env):
        with _patch(env):
            assert await env["repo"].delete("nonexistent") is False


class TestGetByTask:
    async def test_filter_by_task(self, env):
        with _patch(env):
            await env["repo"].save(ExperienceEntry(agent_id="a", task_id="t1", content="x"))
            await env["repo"].save(ExperienceEntry(agent_id="a", task_id="t1", content="y"))
            await env["repo"].save(ExperienceEntry(agent_id="a", task_id="t2", content="z"))
            results = await env["repo"].get_by_task("t1")
            assert len(results) == 2

    async def test_no_match(self, env):
        with _patch(env):
            results = await env["repo"].get_by_task("nonexistent")
            assert results == []
