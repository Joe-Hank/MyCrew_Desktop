"""PM v6 Phase 6 rule-based agent assignment (2026-05-19).

Replaces the previous LLM-driven Phase 6 with a deterministic Python
rule that maps output_paths suffix → Crew. Tests cover:
  - Each canonical suffix routes to the right Crew
  - final_qa overrides to QA Engineer
  - setup tasks skipped
  - Mixed-kind tasks: .cs dominates
  - .prefab disambiguation by title/detail keywords (UI vs VFX vs Scene)
  - Empty output_paths fallback
  - Missing crew row → logged + skipped
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.sub_agents._planner_orchestrator import (
    _assign_performers_by_rule,
    _classify_prefab_owner,
    _pick_crew_for_task,
)
from tests.conftest import FakeCRUD


@pytest.fixture
def env():
    crud = FakeCRUD()
    # Seed all 8 production Crew rows + QA Engineer agent. is_auto_generated=0
    # so _assign_performers_by_rule will find them.
    crud.seed("crews", [
        {"id": "crew_2dart", "name": "2D 美术资产组", "is_auto_generated": 0},
        {"id": "crew_3d", "name": "3D 模型组", "is_auto_generated": 0},
        {"id": "crew_anim", "name": "动画组", "is_auto_generated": 0},
        {"id": "crew_vfx", "name": "特效组", "is_auto_generated": 0},
        {"id": "crew_sys", "name": "系统实现组", "is_auto_generated": 0},
        {"id": "crew_ui", "name": "UI 实现组", "is_auto_generated": 0},
        {"id": "crew_audio", "name": "音频组", "is_auto_generated": 0},
        {"id": "crew_scene", "name": "场景装配组", "is_auto_generated": 0},
        # Auto-generated crew should be ignored
        {"id": "crew_ghost", "name": "Ghost Crew", "is_auto_generated": 1},
    ])
    crud.seed("agents", [
        {"id": "agent_qa", "role": "QA Engineer"},
    ])
    return crud


# ── _pick_crew_for_task (pure unit, no DB) ─────────────────────────


@pytest.mark.parametrize("paths,expected_crew", [
    (["Assets/Scripts/Foo.cs"], "系统实现组"),
    (["Assets/Sprites/Hero.png"], "2D 美术资产组"),
    (["Assets/Sprites/Hero.jpg"], "2D 美术资产组"),
    (["Assets/Models/Tree.fbx"], "3D 模型组"),
    (["Assets/Models/Tree.blend"], "3D 模型组"),
    (["Assets/Audio/bgm.wav"], "音频组"),
    (["Assets/Audio/sfx.mp3"], "音频组"),
    (["Assets/Animations/Idle.anim"], "动画组"),
    (["Assets/Animations/Player.controller"], "动画组"),
    (["Assets/Scenes/Main.unity"], "场景装配组"),
    (["Assets/ScriptableObjects/Config.asset"], "系统实现组"),
    (["Assets/Materials/Wall.mat"], "场景装配组"),
])
def test_canonical_suffix_routes(paths, expected_crew):
    crew, _reason = _pick_crew_for_task({"output_paths": paths, "title": "x"})
    assert crew == expected_crew


def test_mixed_kind_cs_dominates():
    """V5 real case: AudioManager.cs + 4 .wav was misrouted to 音频组,
    leaving the .cs unwritten. Rule says .cs wins so the .cs gets a
    Crew that can produce it (_detect_same_kind_bundling warns the user
    to split the task — but if it slips through, dominate to system)."""
    crew, _ = _pick_crew_for_task({"output_paths": [
        "Assets/Scripts/Audio/AudioManager.cs",
        "Assets/Audio/BGM/bgm.wav",
        "Assets/Audio/SFX/sfx.wav",
    ], "title": "AudioSystem.cs + Audio"})
    assert crew == "系统实现组"


def test_no_recognized_suffix_falls_back():
    crew, reason = _pick_crew_for_task({
        "output_paths": ["random.xyz"], "title": "weird"
    })
    assert crew == "系统实现组"
    assert "无法识别" in reason or "default" in reason.lower()


def test_empty_output_paths_falls_back():
    crew, reason = _pick_crew_for_task({"output_paths": [], "title": "x"})
    assert crew == "系统实现组"
    assert "no output_paths" in reason


# ── .prefab disambiguation ─────────────────────────────────────────


@pytest.mark.parametrize("title,detail,expected", [
    ("HUDController", "Canvas + Image + Text", "UI 实现组"),
    ("MainMenu", "按钮 / 面板", "UI 实现组"),
    ("Explosion VFX", "ParticleSystem 粒子", "特效组"),
    ("Hit Effect", "光效", "特效组"),
    ("Player Prefab", "实例化角色到场景中", "场景装配组"),
])
def test_prefab_classifier(title, detail, expected):
    actual = _classify_prefab_owner({"title": title, "detail": detail})
    assert actual == expected


def test_pure_prefab_dispatch_via_keywords():
    crew, _ = _pick_crew_for_task({
        "output_paths": ["Assets/Prefabs/HUDCanvas.prefab"],
        "title": "HUDCanvas", "detail": "Canvas 含 Text 显示分数",
    })
    assert crew == "UI 实现组"

    crew, _ = _pick_crew_for_task({
        "output_paths": ["Assets/Prefabs/Hit.prefab"],
        "title": "Hit VFX", "detail": "ParticleSystem 受击粒子特效",
    })
    assert crew == "特效组"

    crew, _ = _pick_crew_for_task({
        "output_paths": ["Assets/Prefabs/Player.prefab"],
        "title": "Player", "detail": "玩家实例化到场景",
    })
    assert crew == "场景装配组"


# ── _assign_performers_by_rule (full path, with FakeCRUD) ─────────


@pytest.mark.asyncio
async def test_assignments_skip_setup_and_override_final_qa(env):
    tasks = [
        {"kind": "setup", "output_paths": ["Assets/"], "title": "setup"},
        {"kind": "regular", "output_paths": ["Assets/Scripts/Foo.cs"], "title": "Foo"},
        {"kind": "final_qa", "output_paths": [], "title": "QA"},
    ]
    with patch("agents.sub_agents._planner_orchestrator.crud", env):
        result = await _assign_performers_by_rule(tasks)
    # setup excluded; final_qa → QA Engineer agent; regular → crew_sys
    assert len(result) == 2
    by_idx = {a["task_index"]: a for a in result}
    assert 0 not in by_idx  # setup skipped
    assert by_idx[1]["performer_ref"] == {"kind": "crew", "id": "crew_sys"}
    assert by_idx[2]["performer_ref"] == {"kind": "agent", "id": "agent_qa"}


@pytest.mark.asyncio
async def test_assignments_cover_all_kinds(env):
    tasks = [
        {"kind": "regular", "output_paths": ["Assets/Sprites/A.png"], "title": "sprite"},
        {"kind": "regular", "output_paths": ["Assets/Models/B.fbx"], "title": "model"},
        {"kind": "regular", "output_paths": ["Assets/Audio/C.wav"], "title": "sfx"},
        {"kind": "regular", "output_paths": ["Assets/Scenes/Main.unity"], "title": "scene"},
        {"kind": "regular", "output_paths": ["Assets/Animations/I.anim"], "title": "anim"},
    ]
    with patch("agents.sub_agents._planner_orchestrator.crud", env):
        result = await _assign_performers_by_rule(tasks)
    ids = [a["performer_ref"]["id"] for a in result]
    assert ids == [
        "crew_2dart", "crew_3d", "crew_audio", "crew_scene", "crew_anim",
    ]


@pytest.mark.asyncio
async def test_missing_crew_row_skips_assignment(env):
    """If a tag points at a Crew name not present in DB (data drift),
    the assignment for that task is dropped + logged, not crashed."""
    # Remove 系统实现组 from env (FakeCRUD stores rows in a dict by id)
    env._tables["crews"] = {
        rid: row for rid, row in env._tables["crews"].items()
        if row.get("name") != "系统实现组"
    }
    tasks = [
        {"kind": "regular", "output_paths": ["Foo.cs"], "title": "x"},
    ]
    with patch("agents.sub_agents._planner_orchestrator.crud", env):
        result = await _assign_performers_by_rule(tasks)
    assert result == []
