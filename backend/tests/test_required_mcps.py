"""Tests for workflow_svc.required_mcps — the walk that powers the
TaskHeader MCP chip row + the Start pre-flight gate.

Mocks the DB and the MCP pool so we test pure logic: given some tasks
bound to agents (single or via Crew) whose tools live in specific MCP
servers, the right set of servers comes back with the right tool list.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from services.workflow_svc import WorkflowService
from tests.conftest import FakeCRUD, make_project, make_task


@pytest.fixture
def env():
    crud = FakeCRUD()

    # Project + two tasks: one bound to a single agent, one to a Crew.
    crud.seed("projects", [make_project("proj_1")])
    crud.seed("tasks", [
        {**make_task("t_agent", project_id="proj_1"),
         "agent_id": "agent_alpha",
         "performer_kind": "agent",
         "performer_id": "agent_alpha"},
        {**make_task("t_crew", project_id="proj_1"),
         "agent_id": None,
         "performer_kind": "crew",
         "performer_id": "crew_x"},
    ])
    # The Crew references agents agent_beta + agent_gamma.
    crud.seed("crews", [{
        "id": "crew_x",
        "name": "Test Crew",
        "agent_sequence": json.dumps([
            {"role": "head", "agent_id": "agent_beta"},
            {"role": "qa", "agent_id": "agent_gamma"},
        ]),
    }])
    crud.seed("agents", [
        {"id": "agent_alpha", "role": "alpha",
         "tool_ids": json.dumps(["tool_comfy", "tool_write"])},
        {"id": "agent_beta", "role": "beta",
         "tool_ids": json.dumps(["tool_unity_asset"])},
        {"id": "agent_gamma", "role": "gamma",
         "tool_ids": json.dumps(["tool_unity_asset", "tool_read_console"])},
    ])
    crud.seed("tools", [
        {"id": "tool_comfy", "name": "comfy_enqueue_workflow"},
        {"id": "tool_write", "name": "write_file"},
        {"id": "tool_unity_asset", "name": "manage_asset"},
        {"id": "tool_read_console", "name": "read_console"},
    ])
    crud.seed("mcp_servers", [
        {"id": "mcp_comfy", "name": "comfyui", "enabled": 1,
         "discovered_tools": json.dumps([
             {"name": "comfy_enqueue_workflow"},
             {"name": "comfy_get_history"},
         ])},
        {"id": "mcp_unity", "name": "unity", "enabled": 1,
         "discovered_tools": json.dumps([
             {"name": "manage_asset"},
             {"name": "read_console"},
             {"name": "manage_scene"},
         ])},
        {"id": "mcp_unused", "name": "blender", "enabled": 1,
         "discovered_tools": json.dumps([
             {"name": "execute_blender_code"},
         ])},
        {"id": "mcp_disabled", "name": "tavily", "enabled": 0,
         "discovered_tools": json.dumps([
             {"name": "tavily_search"},
         ])},
    ])
    return crud


class _FakePool:
    def __init__(self, statuses: dict[str, str]) -> None:
        self._statuses = statuses

    def get_all_statuses(self) -> list[dict]:
        return [
            {"server_id": k, "status": v} for k, v in self._statuses.items()
        ]


@pytest.mark.asyncio
async def test_required_servers_intersect_tool_set(env):
    pool = _FakePool({
        "mcp_comfy": "connected",
        "mcp_unity": "disconnected",
        "mcp_unused": "connected",
        "mcp_disabled": "disconnected",
    })
    with patch("services.workflow_svc.crud", env), \
         patch("infra.mcp.pool.mcp_pool", pool):
        svc = WorkflowService()
        result = await svc.required_mcps("proj_1")

    by_name = {s["name"]: s for s in result}
    # comfyui is needed (agent_alpha uses comfy_enqueue_workflow)
    assert "comfyui" in by_name
    assert by_name["comfyui"]["status"] == "connected"
    assert by_name["comfyui"]["tools_used"] == ["comfy_enqueue_workflow"]

    # unity is needed (Crew agents use manage_asset + read_console)
    assert "unity" in by_name
    assert by_name["unity"]["status"] == "disconnected"
    assert sorted(by_name["unity"]["tools_used"]) == [
        "manage_asset", "read_console",
    ]

    # blender NOT needed — no agent uses any blender tool
    assert "blender" not in by_name

    # tavily is disabled in DB → excluded even if it discovered tools
    assert "tavily" not in by_name


@pytest.mark.asyncio
async def test_no_tasks_returns_empty(env):
    pool = _FakePool({})
    env.seed("projects", [make_project("proj_empty")])
    with patch("services.workflow_svc.crud", env), \
         patch("infra.mcp.pool.mcp_pool", pool):
        svc = WorkflowService()
        result = await svc.required_mcps("proj_empty")
    assert result == []
