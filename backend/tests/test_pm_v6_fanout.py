"""PM v6 per-task fan-out — unit tests for helpers (no live LLM).

Covers:
  - _inline_refs flattens $defs/$ref for new single-task schemas
  - _dedup_path_specs renames collisions with _2 / _3 suffixes
  - _run_phase_per_task aggregates N parallel calls + Semaphore caps + partial failures
  - reasoner-swap guards in both _force_tool_call_fallback and _force_tool_call_once
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from agents.sub_agents import _planner_orchestrator as orc
from agents.sub_agents._planner_models import (
    SubmitCodeContractSingleArgs,
    SubmitPathSpecSingleArgs,
    SubmitReviewedTaskSingleArgs,
)


# ── _inline_refs ────────────────────────────────────────────────────


def test_inline_refs_strips_defs_from_all_single_schemas():
    for cls in (
        SubmitReviewedTaskSingleArgs,
        SubmitPathSpecSingleArgs,
        SubmitCodeContractSingleArgs,
    ):
        raw = cls.model_json_schema()
        flat = orc._inline_refs(raw)
        flat_json = json.dumps(flat)
        assert "$ref" not in flat_json, f"{cls.__name__} still has $ref"
        assert "$defs" not in flat_json, f"{cls.__name__} still has $defs"


def test_inline_refs_preserves_field_descriptions():
    raw = SubmitPathSpecSingleArgs.model_json_schema()
    flat = orc._inline_refs(raw)
    # PathSpec.task_index has a description; should survive inlining.
    nested = flat["properties"]["path_spec"]
    assert "properties" in nested
    assert "task_index" in nested["properties"]


# ── _dedup_path_specs ──────────────────────────────────────────────


def test_dedup_path_specs_renames_collisions_in_order():
    specs = [
        {"task_index": 0, "output_paths": ["Assets/Scripts/Foo.cs"]},
        {"task_index": 1, "output_paths": ["Assets/Scripts/Foo.cs"]},
        {"task_index": 2, "output_paths": ["Assets/Scripts/Foo.cs"]},
    ]
    out, hints = orc._dedup_path_specs(specs)
    assert out[0]["output_paths"] == ["Assets/Scripts/Foo.cs"]
    assert out[1]["output_paths"] == ["Assets/Scripts/Foo_2.cs"]
    assert out[2]["output_paths"] == ["Assets/Scripts/Foo_3.cs"]
    assert len(hints) == 2  # two renames logged


def test_dedup_handles_no_extension():
    specs = [
        {"task_index": 0, "output_paths": ["Assets/Folder"]},
        {"task_index": 1, "output_paths": ["Assets/Folder"]},
    ]
    out, hints = orc._dedup_path_specs(specs)
    assert out[1]["output_paths"] == ["Assets/Folder_2"]


def test_dedup_no_collision_passthrough():
    specs = [
        {"task_index": 0, "output_paths": ["a.cs", "b.cs"]},
        {"task_index": 1, "output_paths": ["c.cs"]},
    ]
    out, hints = orc._dedup_path_specs(specs)
    assert hints == []
    assert out[0]["output_paths"] == ["a.cs", "b.cs"]
    assert out[1]["output_paths"] == ["c.cs"]


def test_dedup_skips_empty_strings_and_non_strings():
    specs = [
        {"task_index": 0, "output_paths": ["a.cs", "", None, 123]},
    ]
    out, _ = orc._dedup_path_specs(specs)
    assert out[0]["output_paths"] == ["a.cs"]


# ── _run_phase_per_task ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_phase_per_task_aggregates_results_and_caps_concurrency(monkeypatch):
    """N=5 items, cap=2 → max 2 concurrent, results returned in index order."""
    in_flight = 0
    max_in_flight = 0
    captured_indices: list[int] = []

    async def fake_once(*, submit_tool, system_msg, user_msg, **kw):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.04)
        in_flight -= 1
        # user_msg embeds task_index — extract back for assertion
        idx = int(user_msg.split("task_index = ")[1].split("\n")[0])
        captured_indices.append(idx)
        return {"task": {"task_index": idx, "title": f"t{idx}"}}

    monkeypatch.setattr(orc, "_force_tool_call_once", fake_once)

    items = [{"title": f"t{i}"} for i in range(5)]

    def desc(i, t):
        return f"task_index = {i}\nstuff"

    # Build a minimal fake submit_tool with .name attr
    class _FakeTool:
        name = "submit_x"
        description = "x"
        args_schema = SubmitPathSpecSingleArgs

    results = await orc._run_phase_per_task(
        session_id="s1", phase="review", role="r",
        backstory="b", items=items,
        per_task_description_builder=desc,
        submit_tool_factory=lambda: _FakeTool(),
        provider={"type": "deepseek", "api_key_ref": "x"},
        model_name="deepseek-v4-flash",
        concurrency=2, temperature=0.2, max_tokens=512,
    )

    assert len(results) == 5
    # All items processed
    assert sorted(captured_indices) == [0, 1, 2, 3, 4]
    # Order preserved
    for i, r in enumerate(results):
        assert r is not None
        assert r["task"]["task_index"] == i
    # Concurrency cap respected
    assert max_in_flight <= 2, f"semaphore breach: {max_in_flight}"


@pytest.mark.asyncio
async def test_run_phase_per_task_returns_none_for_failures(monkeypatch):
    """One item returning None doesn't crash; final list aligns with input."""
    async def fake_once(*, submit_tool, system_msg, user_msg, **kw):
        idx = int(user_msg.split("task_index = ")[1].split("\n")[0])
        if idx == 1:
            return None  # simulate this one failed
        return {"task": {"task_index": idx}}

    monkeypatch.setattr(orc, "_force_tool_call_once", fake_once)

    class _FakeTool:
        name = "submit_x"
        description = "x"
        args_schema = SubmitPathSpecSingleArgs

    items = [{"title": f"t{i}"} for i in range(3)]
    results = await orc._run_phase_per_task(
        session_id="s1", phase="p", role="r",
        backstory="b", items=items,
        per_task_description_builder=lambda i, t: f"task_index = {i}\n",
        submit_tool_factory=lambda: _FakeTool(),
        provider={"type": "deepseek"}, model_name="deepseek-v4-flash",
        concurrency=3, temperature=0.2, max_tokens=512,
    )
    assert results[0] is not None
    assert results[1] is None
    assert results[2] is not None


@pytest.mark.asyncio
async def test_run_phase_per_task_empty_items_returns_empty():
    r = await orc._run_phase_per_task(
        session_id="s1", phase="p", role="r",
        backstory="b", items=[],
        per_task_description_builder=lambda i, t: "",
        submit_tool_factory=lambda: None,
        provider={}, model_name="x",
    )
    assert r == []


# ── tool_choice mode (2026-05-19 diagnosis flip) ───────────────────
#
# Originally we used tool_choice={"type":"function","function":{"name":"..."}}
# to force the LLM to call a specific tool. DeepSeek silently routes
# such requests through their reasoner channel and 4xx's, even when
# the explicit model is v4-flash. Standalone diag confirmed only
# tool_choice="auto" works reliably. These tests pin the auto-mode
# choice so we don't regress.


@pytest.mark.asyncio
async def test_force_tool_call_once_uses_auto_mode(monkeypatch):
    captured: dict = {}

    class _FakeChoice:
        class message:
            tool_calls = None
            content = "no tool call"

    class _FakeResp:
        choices = [_FakeChoice()]

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResp()

    import litellm
    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    class _FakeTool:
        name = "submit_x"
        description = "x"
        args_schema = SubmitPathSpecSingleArgs

    await orc._force_tool_call_once(
        submit_tool=_FakeTool(),
        system_msg="sys", user_msg="user",
        provider={"type": "deepseek", "api_key_ref": "x"},
        model_name="deepseek-v4-flash",
        temperature=0.2, max_tokens=512,
    )
    # Must use auto mode; forced modes 4xx on DeepSeek today.
    assert captured.get("tool_choice") == "auto"
    # Tool spec still attached so LLM has a target to pick.
    assert isinstance(captured.get("tools"), list)
    assert captured["tools"][0]["function"]["name"] == "submit_x"
    # System prompt should include the explicit tool-use directive
    sys_msg = captured["messages"][0]["content"]
    assert "submit_x" in sys_msg
    assert "tool_call" in sys_msg or "工具" in sys_msg


@pytest.mark.asyncio
async def test_force_tool_call_fallback_uses_auto_mode(monkeypatch):
    captured: dict = {}

    class _FakeChoice:
        class message:
            tool_calls = None
            content = "no tool call"

    class _FakeResp:
        choices = [_FakeChoice()]

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _FakeResp()

    async def noop_broadcast(*a, **kw):
        return None
    monkeypatch.setattr(orc, "_broadcast", noop_broadcast)

    import litellm
    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    class _FakeTool:
        name = "submit_x"
        description = "x"
        args_schema = SubmitPathSpecSingleArgs

    ok = await orc._force_tool_call_fallback(
        session_id="s1", phase="p",
        submit_tool=_FakeTool(),
        backstory="b", description="d",
        provider={"type": "deepseek", "api_key_ref": "x"},
        model_name="deepseek-v4-flash",
        temperature=0.2, max_tokens=512,
    )
    assert ok is False  # fake returned no tool_calls → False
    assert captured.get("tool_choice") == "auto"
