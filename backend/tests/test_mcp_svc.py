"""Tests for McpService — CRUD, pool operations, serialization."""
import json
from unittest.mock import patch

import pytest

from services.mcp_svc import McpService
from tests.conftest import FakeCRUD, FakeMCPPool


@pytest.fixture
def env():
    crud = FakeCRUD()
    pool = FakeMCPPool()
    svc = McpService()
    svc._pool = pool
    return {"svc": svc, "crud": crud, "pool": pool}


def _patch(env):
    return patch("services.mcp_svc.crud", env["crud"])


class TestCreateServer:
    async def test_basic_create(self, env):
        with _patch(env):
            result = await env["svc"].create_server({
                "name": "Blender MCP",
                "transport": "stdio",
                "command": "python",
                "args": ["-m", "blender_mcp"],
            })
            assert result["name"] == "Blender MCP"
            assert result["transport"] == "stdio"
            assert result["args"] == ["-m", "blender_mcp"]
            assert result["enabled"] is True

    async def test_default_values(self, env):
        with _patch(env):
            result = await env["svc"].create_server({"name": "Test"})
            assert result["transport"] == "stdio"
            assert result["auto_start"] is True
            assert result["timeout"] == 30


class TestGetServer:
    async def test_get_with_status(self, env):
        with _patch(env):
            created = await env["svc"].create_server({"name": "S1"})
            env["pool"]._statuses[created["id"]] = "connected"

            result = await env["svc"].get_server(created["id"])
            assert result["runtime_status"] == "connected"

    async def test_get_nonexistent(self, env):
        with _patch(env):
            assert await env["svc"].get_server("nonexistent") is None


class TestListServers:
    async def test_list_with_statuses(self, env):
        with _patch(env):
            s1 = await env["svc"].create_server({"name": "S1"})
            s2 = await env["svc"].create_server({"name": "S2"})
            env["pool"]._statuses[s1["id"]] = "connected"

            result = await env["svc"].list_servers()
            assert len(result) == 2
            statuses = {s["name"]: s["runtime_status"] for s in result}
            assert statuses["S1"] == "connected"
            assert statuses["S2"] == "disconnected"


class TestUpdateServer:
    async def test_update_fields(self, env):
        with _patch(env):
            created = await env["svc"].create_server({"name": "S1"})
            result = await env["svc"].update_server(created["id"], {"name": "S1-Updated", "enabled": False})
            assert result["name"] == "S1-Updated"
            assert result["enabled"] is False

    async def test_update_nonexistent(self, env):
        with _patch(env):
            result = await env["svc"].update_server("nonexistent", {"name": "X"})
            assert result is None


class TestDeleteServer:
    async def test_removes_from_pool_and_db(self, env):
        with _patch(env):
            created = await env["svc"].create_server({"name": "S1"})
            env["pool"]._statuses[created["id"]] = "connected"

            await env["svc"].delete_server(created["id"])
            assert created["id"] not in env["pool"]._statuses
            assert await env["crud"].get_by_id("mcp_servers", created["id"]) is None


class TestPoolOperations:
    async def test_connect(self, env):
        with _patch(env):
            created = await env["svc"].create_server({"name": "S1"})
            result = await env["svc"].connect_server(created["id"])
            assert result["status"] == "connected"

    async def test_connect_nonexistent(self, env):
        with _patch(env):
            with pytest.raises(KeyError, match="not found"):
                await env["svc"].connect_server("nonexistent")

    async def test_disconnect(self, env):
        with _patch(env):
            created = await env["svc"].create_server({"name": "S1"})
            await env["svc"].connect_server(created["id"])
            await env["svc"].disconnect_server(created["id"])
            assert env["pool"].get_connection_status(created["id"]) == "disconnected"

    async def test_restart_disconnected(self, env):
        with _patch(env):
            created = await env["svc"].create_server({"name": "S1"})
            result = await env["svc"].restart_server(created["id"])
            assert result["status"] == "connected"

    async def test_call_tool(self, env):
        with _patch(env):
            result = await env["svc"].call_tool("s1", "my_tool", {"arg": "val"})
            assert json.loads(result) == {"result": "ok"}


class TestStatusSummary:
    async def test_summary(self, env):
        with _patch(env):
            s1 = await env["svc"].create_server({"name": "S1"})
            s2 = await env["svc"].create_server({"name": "S2"})
            env["pool"]._statuses[s1["id"]] = "connected"

            result = await env["svc"].get_status_summary()
            assert result["total"] == 2
            assert result["enabled"] == 2
            assert result["online"] == 1


class TestSerialization:
    def test_serialize_json_fields(self):
        svc = McpService()
        data = {"args": ["-m", "test"], "env_ref": {"KEY": "val"}, "discovered_tools": []}
        result = svc._serialize(data)
        assert isinstance(result["args"], str)
        assert json.loads(result["args"]) == ["-m", "test"]

    def test_deserialize_json_fields(self):
        svc = McpService()
        data = {
            "args": '["-m", "test"]',
            "env_ref": '{"KEY": "val"}',
            "discovered_tools": "[]",
            "enabled": 1,
            "auto_start": 0,
        }
        result = svc._deserialize(data)
        assert result["args"] == ["-m", "test"]
        assert result["enabled"] is True
        assert result["auto_start"] is False

    def test_deserialize_invalid_json_passthrough(self):
        svc = McpService()
        data = {"args": "not json", "enabled": 1, "auto_start": 1}
        result = svc._deserialize(data)
        assert result["args"] == "not json"
