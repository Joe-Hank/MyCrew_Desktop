"""Stage-E smoke tests: emit_output enforces the PM-declared
``task.output_paths`` contract regardless of how the agent shapes the
payload.

Pairs with test_emit_output_paths.py (the existing payload-field
heuristic) — this one validates the *bound contract* layer added in
Stage E (2026-05-16).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.builtin.local.emit_output import make_emit_output_tool


def test_no_contract_skips_check(tmp_path):
    """When PM declares no output_paths, only the heuristic runs."""
    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path),
        expected_paths=None,
    )
    # Empty payload, no expected_paths -> passes through.
    out = tool._run({"text": "done"})
    assert out.startswith("OK")


def test_contract_paths_missing_rejected(tmp_path):
    """Agent ships a payload but the PM-mandated file isn't on disk."""
    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path),
        expected_paths=["Assets/Sprites/player.png"],
    )
    # Agent uses a custom field name; old heuristic wouldn't catch it.
    out = tool._run({"generated_files": ["Assets/Sprites/player.png"]})
    assert out.startswith("[ValidationError]")
    assert "task.output_paths declares files" in out
    assert "Assets/Sprites/player.png" in out


def test_contract_paths_satisfied_passes(tmp_path):
    """All PM-mandated files exist — emit_output succeeds even though
    the agent's payload uses a non-whitelist field name."""
    asset = tmp_path / "Assets" / "Sprites" / "player.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path),
        expected_paths=["Assets/Sprites/player.png"],
    )
    out = tool._run({"generated_files": ["Assets/Sprites/player.png"]})
    assert out.startswith("OK")


def test_absolute_path_in_contract(tmp_path):
    """Absolute paths bypass the project_root prefix step."""
    asset = tmp_path / "level.json"
    asset.write_text("{}", encoding="utf-8")

    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path / "ignored_root"),
        expected_paths=[str(asset.resolve())],
    )
    out = tool._run({"summary": "ok"})
    assert out.startswith("OK")


def test_partial_contract_satisfaction(tmp_path):
    """Only some of the contract paths exist — error lists the missing ones."""
    have = tmp_path / "a.png"
    have.write_bytes(b"x")
    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path),
        expected_paths=["a.png", "b.png", "c.png"],
    )
    out = tool._run({"any": "shape"})
    assert out.startswith("[ValidationError]")
    assert "b.png" in out and "c.png" in out
    assert "a.png" not in out  # a was OK, so shouldn't be listed


def test_empty_contract_list_is_valid_no_files_expected(tmp_path):
    """Empty list explicitly says "no files to produce" — emit succeeds
    even with no produced files."""
    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path),
        expected_paths=[],  # explicit empty contract
    )
    out = tool._run({"summary": "design doc only"})
    assert out.startswith("OK")


def test_head_role_bypasses_path_existence_check(tmp_path):
    """Head steps emit SPECS only — files will be created by downstream
    Executor. The on-disk existence check would deadlock because Head
    has no write_file tool (seed_crews._HEAD_READONLY removed it
    intentionally). Verify step_role='head' skips the check so Head
    can declare future file_paths without first creating them.

    Real-world repro: 2026-05-20 水果忍者 project — System Designer
    (head of 系统实现组) emitted a perfectly valid C# spec, but the
    validator rejected it with "files do not exist on disk", agent
    gave up and wrote verdict='fail'.
    """
    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path),
        expected_paths=["Assets/Scripts/FruitSpawner.cs"],
        step_role="head",  # ← key
    )
    # File doesn't exist yet — this would fail without the bypass.
    out = tool._run({
        "file_paths": ["Assets/Scripts/FruitSpawner.cs"],
        "summary": "spec body",
    })
    assert out.startswith("OK"), out


def test_executor_role_keeps_path_existence_check(tmp_path):
    """Executor IS supposed to have created files — bypass must not
    leak from head to executor. Files-missing → still rejected."""
    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path),
        expected_paths=["Assets/Scripts/FruitSpawner.cs"],
        step_role="executor",
    )
    out = tool._run({
        "file_paths": ["Assets/Scripts/FruitSpawner.cs"],
    })
    assert out.startswith("[ValidationError]")
    assert "FruitSpawner.cs" in out


def test_qa_role_keeps_path_existence_check(tmp_path):
    """QA verifies — same enforcement as Executor."""
    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path),
        expected_paths=["Assets/Scripts/FruitSpawner.cs"],
        step_role="qa",
    )
    out = tool._run({"file_paths": ["Assets/Scripts/FruitSpawner.cs"]})
    assert out.startswith("[ValidationError]")


def test_step_role_none_defaults_to_enforce(tmp_path):
    """Unspecified step_role (legacy callers / non-Crew flows) keeps
    the historical enforce-on behaviour to avoid silently weakening
    existing checks."""
    tool = make_emit_output_tool(
        task_id="t1",
        output_schema={},
        project_root=str(tmp_path),
        expected_paths=["Assets/foo.png"],
        # step_role omitted
    )
    out = tool._run({"file_paths": ["Assets/foo.png"]})
    assert out.startswith("[ValidationError]")
