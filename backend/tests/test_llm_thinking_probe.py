"""Stage: /llm/probe-thinking heuristic + cache (2026-05-17).

Locks in the per-provider rules so a stray rename (e.g. Anthropic
ships claude-opus-5 next year) doesn't silently regress the toggle
gate. The probe writes back to llm_models.supports_thinking when an
existing row is found — separately verified by the integration test
at the bottom.
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "ptype,model,expected",
    [
        # Anthropic: 3.7 + 4.x families
        ("anthropic", "claude-3-7-sonnet-20250219", True),
        ("anthropic", "claude-opus-4-20250514", True),
        ("anthropic", "claude-sonnet-4-5", True),
        ("anthropic", "claude-haiku-4-1", True),
        ("anthropic", "claude-3-5-sonnet-20241022", False),
        ("anthropic", "claude-3-haiku-20240307", False),
        # OpenAI: o-series + gpt-5
        ("openai", "o1-preview", True),
        ("openai", "o3-mini", True),
        ("openai", "o4-mini", True),
        ("openai", "gpt-5-thinking", True),
        ("openai", "gpt-4o", False),
        ("openai", "gpt-4-turbo", False),
        # DeepSeek
        ("deepseek", "deepseek-reasoner", True),
        ("deepseek", "deepseek-r1", True),
        ("deepseek", "deepseek-chat", False),
        ("deepseek", "deepseek-coder", False),
        # Qwen QwQ
        ("qwen", "qwq-32b-preview", True),
        ("qwen", "qwen-plus-thinking", True),
        ("qwen", "qwen-turbo", False),
        # Gemini
        ("gemini", "gemini-2.5-flash-thinking", True),
        ("gemini", "gemini-1.5-pro", False),
        # Unknown providers default false (safer than false-positive)
        ("ollama", "llama3", False),
        ("custom", "anything-goes", False),
        ("", "", False),
    ],
)
def test_heuristic_supports_thinking(ptype, model, expected):
    from services.llm_svc import LlmService
    assert LlmService._heuristic_supports_thinking(ptype, model) is expected


@pytest.mark.asyncio
async def test_probe_thinking_caches_to_db(monkeypatch):
    """When called with model_id, probe should write supports_thinking
    back to the llm_models row so subsequent /llm/providers reads
    reflect it without re-probing."""
    from infra.repo import crud
    from services.llm_svc import llm_svc

    provider_row = {"id": "prov_x", "type": "anthropic", "name": "Test"}
    model_row = {
        "id": "mdl_x",
        "provider_id": "prov_x",
        "model_name": "claude-opus-4-20250514",
        "supports_thinking": 0,
    }
    saved: dict[str, dict] = {}

    async def fake_get_by_id(table, pk):
        if table == "llm_models" and pk == "mdl_x":
            return model_row
        if table == "llm_providers" and pk == "prov_x":
            return provider_row
        return None

    async def fake_update_by_id(table, pk, fields):
        saved[(table, pk)] = fields
        return {**model_row, **fields}

    monkeypatch.setattr(crud, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(crud, "update_by_id", fake_update_by_id)

    result = await llm_svc.probe_thinking(model_id="mdl_x")
    assert result["supports_thinking"] is True
    assert result["cached"] is True
    assert saved[("llm_models", "mdl_x")] == {"supports_thinking": 1}


@pytest.mark.asyncio
async def test_probe_thinking_without_model_row(monkeypatch):
    """Probe with provider_id + model_name only (no model row yet).
    Should return the heuristic verdict but report cached=False —
    nothing was written to the DB."""
    from infra.repo import crud
    from services.llm_svc import llm_svc

    async def fake_get_by_id(table, pk):
        if table == "llm_providers" and pk == "prov_y":
            return {"id": "prov_y", "type": "openai", "name": "Test OAI"}
        return None

    async def fake_get_all(table, *_args, **_kwargs):
        return []

    monkeypatch.setattr(crud, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(crud, "get_all", fake_get_all)

    res = await llm_svc.probe_thinking(
        provider_id="prov_y", model_name="o3-mini",
    )
    assert res["supports_thinking"] is True
    assert res["cached"] is False
    assert res["provider_type"] == "openai"
