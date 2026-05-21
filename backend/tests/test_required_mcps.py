"""Tests for workflow_svc.required_mcps (2026-05-19 template-driven rewrite).

Replaces the old agent.tool_ids → mcp.discovered_tools intersection.
The new logic reads `project.template_id` and looks up
`TEMPLATE_REQUIRED_MCPS` to get the hard-coded whitelist.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from services.workflow_svc import WorkflowService
from tests.conftest import FakeCRUD, make_project


@pytest.fixture
def env():
    crud = FakeCRUD()

    # Three projects, three templates
    crud.seed("projects", [
        {**make_project("proj_2d"), "template_id": "unity_universal_2d"},
        {**make_project("proj_3d"), "template_id": "unity_universal_3d"},
        {**make_project("proj_legacy"), "template_id": None},
    ])
    crud.seed("mcp_servers", [
        {"id": "mcp_unity", "name": "unity", "enabled": 1, "discovered_tools": "[]"},
        {"id": "mcp_comfy", "name": "comfyui", "enabled": 1, "discovered_tools": "[]"},
        {"id": "mcp_blender", "name": "blender", "enabled": 1, "discovered_tools": "[]"},
        {"id": "mcp_tavily", "name": "tavily", "enabled": 1, "discovered_tools": "[]"},
        {"id": "mcp_off", "name": "git", "enabled": 0, "discovered_tools": "[]"},
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
async def test_2d_template_requires_unity_and_comfyui_not_blender(env):
    pool = _FakePool({
        "mcp_unity": "connected",
        "mcp_comfy": "disconnected",
        "mcp_blender": "connected",
    })
    with patch("services.workflow_svc.crud", env), \
         patch("infra.mcp.pool.mcp_pool", pool):
        svc = WorkflowService()
        result = await svc.required_mcps("proj_2d")

    names = {s["name"] for s in result}
    assert names == {"unity", "comfyui"}, \
        f"2D should require {{unity, comfyui}}; got {names}"
    by_name = {s["name"]: s for s in result}
    assert by_name["unity"]["status"] == "connected"
    assert by_name["comfyui"]["status"] == "disconnected"


@pytest.mark.asyncio
async def test_3d_template_requires_all_three(env):
    pool = _FakePool({
        "mcp_unity": "connected",
        "mcp_comfy": "connected",
        "mcp_blender": "connected",
    })
    with patch("services.workflow_svc.crud", env), \
         patch("infra.mcp.pool.mcp_pool", pool):
        svc = WorkflowService()
        result = await svc.required_mcps("proj_3d")

    names = {s["name"] for s in result}
    assert names == {"unity", "comfyui", "blender"}, \
        f"3D should require {{unity, comfyui, blender}}; got {names}"


@pytest.mark.asyncio
async def test_legacy_template_returns_empty(env):
    pool = _FakePool({})
    with patch("services.workflow_svc.crud", env), \
         patch("infra.mcp.pool.mcp_pool", pool):
        svc = WorkflowService()
        result = await svc.required_mcps("proj_legacy")
    assert result == [], "legacy (no template) should not block start"


@pytest.mark.asyncio
async def test_disabled_mcp_excluded(env):
    """Even if the template would whitelist a server, enabled=0 means
    the user has explicitly turned it off — don't gate on it."""
    # Patch the whitelist for this test so we don't depend on the
    # production set.
    from services import template_cloner_svc
    with patch.object(
        template_cloner_svc, "TEMPLATE_REQUIRED_MCPS",
        {"unity_universal_2d": {"unity", "git"}},  # git is disabled in env
    ):
        pool = _FakePool({"mcp_unity": "connected"})
        with patch("services.workflow_svc.crud", env), \
             patch("infra.mcp.pool.mcp_pool", pool):
            svc = WorkflowService()
            result = await svc.required_mcps("proj_2d")

    names = {s["name"] for s in result}
    # `git` is whitelisted but disabled — must NOT appear as required
    assert "git" not in names
    assert names == {"unity"}


@pytest.mark.asyncio
async def test_missing_required_mcp_surfaces_as_not_configured(env):
    """A whitelisted MCP that the user hasn't configured at all should
    show as status='not_configured' so the UI can flag it explicitly."""
    from services import template_cloner_svc
    with patch.object(
        template_cloner_svc, "TEMPLATE_REQUIRED_MCPS",
        {"unity_universal_2d": {"unity", "neverheardofthis_mcp"}},
    ):
        pool = _FakePool({"mcp_unity": "connected"})
        with patch("services.workflow_svc.crud", env), \
             patch("infra.mcp.pool.mcp_pool", pool):
            svc = WorkflowService()
            result = await svc.required_mcps("proj_2d")

    by_name = {s["name"]: s for s in result}
    assert by_name["unity"]["status"] == "connected"
    assert "neverheardofthis_mcp" in by_name
    assert by_name["neverheardofthis_mcp"]["status"] == "not_configured"
    assert by_name["neverheardofthis_mcp"]["server_id"] == ""
