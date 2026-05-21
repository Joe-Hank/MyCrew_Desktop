"""Stage-B smoke tests: Crew pool data integrity + idempotent seed.

Catches the kind of regressions that only show up at runtime: a step
references an agent role nobody declared; a head is missing; a Crew
has no QA. These tests run against the in-memory FakeCRUD so they
don't need migrations or a real DB.
"""
from __future__ import annotations

import json

import pytest

from bootstrap.seed_crews import (
    SEED_AGENTS,
    SEED_CREWS,
    _STEP_PREAMBLE,
    ensure_crew_pool,
)


# ── Static data shape ──────────────────────────────────────────────

def test_every_step_resolves_to_an_agent():
    agent_roles = {a["role"] for a in SEED_AGENTS}
    for crew in SEED_CREWS:
        for step in crew["sequence"]:
            assert step["agent_role"] in agent_roles, (
                f"Crew '{crew['name']}' step uses unknown agent role "
                f"'{step['agent_role']}'"
            )


def test_every_crew_has_head_executor_qa():
    for crew in SEED_CREWS:
        roles = [s["role"] for s in crew["sequence"]]
        assert "head" in roles, f"{crew['name']} missing head"
        assert "qa" in roles, f"{crew['name']} missing QA"
        # Executor is optional only for "head-only spec" Crews — none exist
        assert "executor" in roles, f"{crew['name']} missing executor"
        # Head must be first, QA must be last
        assert roles[0] == "head", f"{crew['name']} head must be first"
        assert roles[-1] == "qa", f"{crew['name']} QA must be last"


def test_step_instructions_carry_preamble():
    for crew in SEED_CREWS:
        for step in crew["sequence"]:
            assert step["step_instructions"].startswith(_STEP_PREAMBLE.strip()[:30]), (
                f"{crew['name']} step '{step['agent_role']}' missing PM-contract preamble"
            )


def test_applicable_scenarios_non_empty():
    for crew in SEED_CREWS:
        s = crew["applicable_scenarios"]
        assert s and len(s) > 5, f"{crew['name']} needs applicable_scenarios"


def test_eight_crews_exactly():
    assert len(SEED_CREWS) == 8
    names = {c["name"] for c in SEED_CREWS}
    expected = {
        # 2026-05-19: "美术资产组" → "2D 美术资产组" rename to make
        # Phase 5 routing's 2D vs 3D distinction harder to miss.
        "2D 美术资产组", "3D 模型组", "动画组", "特效组",
        "系统实现组", "UI 实现组",
        "音频组", "场景装配组",
    }
    assert names == expected


def test_audio_synthesizer_uses_synth_tool():
    synth = next(a for a in SEED_AGENTS if a["role"] == "Audio Synthesizer")
    assert "synth_8bit_sfx" in synth["tools"]


def test_unity_developer_has_full_unity_toolset():
    udev = next(a for a in SEED_AGENTS if a["role"] == "Unity Developer")
    # The plan specifies the full Unity MCP set; spot-check the core scene/component/asset trio
    for required in ("manage_scene", "manage_gameobject", "manage_components",
                     "manage_asset", "manage_prefabs", "create_script", "read_console"):
        assert required in udev["tools"], f"Unity Developer must carry {required}"


def test_qa_engineer_has_diagnostic_tools():
    qa = next(a for a in SEED_AGENTS if a["role"] == "QA Engineer")
    for required in ("read_console", "manage_editor", "find_in_file",
                     "read_file_local", "list_directory_local"):
        assert required in qa["tools"], f"QA must carry {required}"


# ── End-to-end seed via FakeCRUD ───────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_crew_pool_inserts_rows(fake_crud, monkeypatch):
    # Patch the global `crud` module that seed_crews imports
    import bootstrap.seed_crews as sc
    monkeypatch.setattr(sc, "crud", fake_crud)

    # Pretend deepseek-flash is configured so seeded agents get an llm_id
    fake_crud.seed("llm_providers", [{"id": "prov_deepseek"}])
    fake_crud.seed("llm_models", [
        {"id": "m1", "provider_id": "prov_deepseek", "model_name": "deepseek-chat-flash"},
    ])

    # Pretend every tool name resolves
    tool_name_to_id = {
        n: f"tool_{n}" for n in {
            *sum([a["tools"] for a in SEED_AGENTS], []),
        }
    }

    result = await ensure_crew_pool(tool_name_to_id)

    # All 8 Crews seeded
    assert len(result) == 8
    crews_table = await fake_crud.get_all("crews")
    assert len(crews_table) == 8
    for c in crews_table:
        seq = json.loads(c["agent_sequence"])
        assert seq and seq[0]["role"] == "head" and seq[-1]["role"] == "qa"
        assert c["applicable_scenarios"]

    # All 14 agents seeded
    agents_table = await fake_crud.get_all("agents")
    assert len(agents_table) == len(SEED_AGENTS)


@pytest.mark.asyncio
async def test_ensure_crew_pool_is_idempotent(fake_crud, monkeypatch):
    import bootstrap.seed_crews as sc
    monkeypatch.setattr(sc, "crud", fake_crud)
    fake_crud.seed("llm_providers", [{"id": "prov_deepseek"}])
    fake_crud.seed("llm_models", [
        {"id": "m1", "provider_id": "prov_deepseek", "model_name": "deepseek-chat-flash"},
    ])
    tools = {n: f"tool_{n}" for n in {*sum([a["tools"] for a in SEED_AGENTS], [])}}

    first = await ensure_crew_pool(tools)
    second = await ensure_crew_pool(tools)
    assert first == second, "Idempotent seed must return same ids on re-run"

    # No duplicates
    assert len(await fake_crud.get_all("crews")) == 8
    assert len(await fake_crud.get_all("agents")) == len(SEED_AGENTS)
