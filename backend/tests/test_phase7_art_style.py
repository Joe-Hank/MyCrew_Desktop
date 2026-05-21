"""Tests for PM Phase 7 (StyleArchitect) — image flow v2 (2026-05-20).

Coverage:
  - `_project_has_art_tasks` gating (only fires on projects with image
    output tasks; pure code projects skip Phase 7)
  - ArtStyleSpec Pydantic schema validation
  - art_style_spec persistence via blueprint_writer
  - workflow_svc._load_art_style_spec reads back what was written
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.sub_agents._planner_models import ArtStyleSpec, SubmitArtStyleSpecArgs
from agents.sub_agents._planner_orchestrator import _project_has_art_tasks
from services.blueprint_writer import write_blueprint_to_disk


# ── _project_has_art_tasks gating ─────────────────────────────────


def test_art_gate_triggers_on_png():
    tasks = [
        {"output_paths": ["Assets/Sprites/Hero.png"]},
        {"output_paths": ["Assets/Scripts/Game.cs"]},
    ]
    assert _project_has_art_tasks(tasks) is True


def test_art_gate_triggers_on_jpg_jpeg_tga_psd():
    for ext in ("jpg", "jpeg", "tga", "psd"):
        assert _project_has_art_tasks([
            {"output_paths": [f"Assets/x.{ext}"]},
        ]) is True


def test_art_gate_skips_pure_code_project():
    tasks = [
        {"output_paths": ["Assets/Scripts/Player.cs"]},
        {"output_paths": ["Assets/Scripts/Enemy.cs"]},
    ]
    assert _project_has_art_tasks(tasks) is False


def test_art_gate_handles_json_string_form():
    """task.output_paths can arrive as either a list (Python in
    planner_cache) or a JSON-encoded string (DB read). Both must work."""
    tasks = [{"output_paths": json.dumps(["Assets/icon.png"])}]
    assert _project_has_art_tasks(tasks) is True


def test_art_gate_empty_or_malformed_input():
    assert _project_has_art_tasks([]) is False
    assert _project_has_art_tasks([{}]) is False
    assert _project_has_art_tasks([{"output_paths": None}]) is False
    assert _project_has_art_tasks([{"output_paths": "not json {{"}]) is False


def test_art_gate_ignores_anim_unity_prefab():
    """Animation / scene / prefab files don't trigger ArtStyle — they
    don't need a ComfyUI style prompt."""
    tasks = [
        {"output_paths": ["Assets/Animations/Walk.anim"]},
        {"output_paths": ["Assets/Scenes/Main.unity"]},
        {"output_paths": ["Assets/Prefabs/Hero.prefab"]},
    ]
    assert _project_has_art_tasks(tasks) is False


# ── ArtStyleSpec schema validation ───────────────────────────────


def test_art_style_spec_minimum_valid():
    """Minimum acceptable spec: required fields populated, optional
    model_params + fallback_style_prompt take defaults."""
    spec = ArtStyleSpec(
        style_prompt="pixel art, 16-bit retro",
        checkpoint="cyberpunk.safetensors",
        background_mode="pixel_pil",
        rationale="像素风兜底，跟项目调性匹配",
    )
    assert spec.background_mode == "pixel_pil"
    assert spec.fallback_style_prompt  # default present
    assert spec.model_params["steps"] == 20


def test_art_style_spec_rejects_invalid_background_mode():
    with pytest.raises(Exception):
        ArtStyleSpec(
            style_prompt="x", checkpoint="c", rationale="r",
            background_mode="invalid_mode",  # not in Literal
        )


def test_submit_art_style_spec_args_round_trip():
    """SubmitArtStyleSpecArgs is what the tool's args_schema validates.
    Should accept either a dict or an ArtStyleSpec instance."""
    args = SubmitArtStyleSpecArgs(spec=ArtStyleSpec(
        style_prompt="x", checkpoint="c.safetensors",
        background_mode="ai_node", rationale="r",
    ))
    assert args.spec.background_mode == "ai_node"


# ── blueprint_writer persistence ─────────────────────────────────


def test_blueprint_writer_drops_art_style_json(tmp_path, monkeypatch):
    """When art_style_spec is passed, blueprint_writer writes
    `.mycrew_pending/art_style.json` alongside `architecture.md`."""
    # Point OUTPUT_DIR at tmp.
    import bootstrap.paths as paths_mod
    import services.blueprint_writer as bw_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(bw_mod, "OUTPUT_DIR", tmp_path)

    project = {"id": "proj_x", "name": "Test"}
    spec_dict = {
        "style_prompt": "pixel art, 16-bit",
        "fallback_style_prompt": "pixel art fallback",
        "checkpoint": "cyberpunk.safetensors",
        "background_mode": "pixel_pil",
        "model_params": {"steps": 20, "cfg": 6.5, "sampler": "euler", "scheduler": "normal"},
        "rationale": "项目像素风",
    }
    base, _pending = write_blueprint_to_disk(
        project, "# overview", tasks=[],
        art_style_spec=spec_dict,
    )
    spec_path = base / "art_style.json"
    assert spec_path.exists()
    loaded = json.loads(spec_path.read_text(encoding="utf-8"))
    assert loaded == spec_dict


def test_blueprint_writer_skips_when_spec_is_none(tmp_path, monkeypatch):
    """No spec → no `.mycrew_pending/art_style.json` created."""
    import bootstrap.paths as paths_mod
    import services.blueprint_writer as bw_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(bw_mod, "OUTPUT_DIR", tmp_path)

    project = {"id": "proj_y", "name": "Code Only"}
    base, _pending = write_blueprint_to_disk(
        project, "# overview", tasks=[],
        # art_style_spec omitted entirely
    )
    assert not (base / "art_style.json").exists()


def test_blueprint_writer_skips_when_spec_empty_dict(tmp_path, monkeypatch):
    """Empty dict is treated same as None — don't drop an empty file."""
    import bootstrap.paths as paths_mod
    import services.blueprint_writer as bw_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(bw_mod, "OUTPUT_DIR", tmp_path)

    project = {"id": "proj_z", "name": "Empty Spec"}
    base, _pending = write_blueprint_to_disk(
        project, "# overview", tasks=[],
        art_style_spec={},
    )
    assert not (base / "art_style.json").exists()


# ── workflow_svc._load_art_style_spec ─────────────────────────────


@pytest.mark.asyncio
async def test_load_art_style_spec_reads_back_written_file(
    tmp_path, monkeypatch,
):
    """End-to-end: write a spec via blueprint_writer, then read it back
    through workflow_svc — bit-exact match.

    Note: blueprint_writer imports OUTPUT_DIR at module top, so patching
    paths_mod.OUTPUT_DIR alone doesn't redirect its writes — we also
    have to patch the name in the blueprint_writer module's namespace.
    Same for workflow_svc.
    """
    import bootstrap.paths as paths_mod
    import services.blueprint_writer as bw_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(bw_mod, "OUTPUT_DIR", tmp_path)

    project = {"id": "proj_e2e", "name": "Test"}
    spec_dict = {
        "style_prompt": "anime cel-shaded",
        "fallback_style_prompt": "pixel art fallback",
        "checkpoint": "cyberpunk.safetensors",
        "background_mode": "ai_node",
        "model_params": {"steps": 30, "cfg": 7.0, "sampler": "dpmpp_2m", "scheduler": "karras"},
        "rationale": "anime 风格匹配",
    }
    write_blueprint_to_disk(project, "x", [], art_style_spec=spec_dict)

    from services.workflow_svc import workflow_svc
    loaded = await workflow_svc._load_art_style_spec("proj_e2e")
    assert loaded == spec_dict


@pytest.mark.asyncio
async def test_load_art_style_spec_returns_none_for_missing_file(
    tmp_path, monkeypatch,
):
    """No file → None. Should never raise — Crew runs on default style
    if the file is missing."""
    import bootstrap.paths as paths_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)
    from services.workflow_svc import workflow_svc
    assert await workflow_svc._load_art_style_spec("proj_none") is None


@pytest.mark.asyncio
async def test_load_art_style_spec_returns_none_for_malformed_json(
    tmp_path, monkeypatch,
):
    """Corrupt file → None + warning log (caller should handle missing
    gracefully)."""
    import bootstrap.paths as paths_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)
    pending = tmp_path / "proj_bad" / ".mycrew_pending"
    pending.mkdir(parents=True)
    (pending / "art_style.json").write_text("{ not valid json")

    from services.workflow_svc import workflow_svc
    assert await workflow_svc._load_art_style_spec("proj_bad") is None


@pytest.mark.asyncio
async def test_load_art_style_spec_returns_none_for_non_dict(
    tmp_path, monkeypatch,
):
    """If the file deserializes to a non-dict (e.g. someone wrote a
    list by mistake), refuse it cleanly."""
    import bootstrap.paths as paths_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)
    pending = tmp_path / "proj_list" / ".mycrew_pending"
    pending.mkdir(parents=True)
    (pending / "art_style.json").write_text(json.dumps(["not", "a", "dict"]))

    from services.workflow_svc import workflow_svc
    assert await workflow_svc._load_art_style_spec("proj_list") is None
