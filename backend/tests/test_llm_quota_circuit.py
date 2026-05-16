"""Stage: sticky-skip on failed LLM quota probes (2026-05-17).

Regression: the same two providers' availability-check warnings were
flooding the backend log every 30s after each cache miss. The fix
adds a per-provider skip set populated on first failure; only
get_quota(force=True) (the home-page 「刷新」 button) clears it +
re-probes.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def env():
    """Reset the singleton's state between tests. We have to clear
    both class AND instance attributes because the production code's
    `self._unavailable_provider_ids = set()` (on force=True) creates
    an instance attribute that would otherwise persist across tests."""
    from services.llm_svc import LlmService, llm_svc
    for attr in (
        "_quota_cache", "_quota_cache_at", "_unavailable_provider_ids",
    ):
        llm_svc.__dict__.pop(attr, None)
    LlmService._quota_cache = None
    LlmService._quota_cache_at = 0.0
    LlmService._unavailable_provider_ids = set()
    return llm_svc


@pytest.mark.asyncio
async def test_first_fail_marks_provider_skipped(env, monkeypatch):
    providers = [
        {"id": "p1", "name": "P1", "type": "anthropic"},
        {"id": "p2", "name": "P2", "type": "deepseek"},
    ]

    async def fake_get_all(table, *_):
        return providers if table == "llm_providers" else []

    probe_calls: list[str] = []

    async def fake_probe(self, p):
        probe_calls.append(p["id"])
        return {
            "provider_id": p["id"],
            "name": p["name"],
            "type": p["type"],
            "display": "unavailable",  # both fail
            "value": None,
            "raw": None,
        }

    monkeypatch.setattr("services.llm_svc.crud.get_all", fake_get_all)
    monkeypatch.setattr(
        "services.llm_svc.LlmService._probe_provider_quota", fake_probe,
    )

    # First call probes both; both fail → both end up in skip set.
    out = await env.get_quota()
    assert len(out) == 2
    assert probe_calls == ["p1", "p2"]
    assert env._unavailable_provider_ids == {"p1", "p2"}


@pytest.mark.asyncio
async def test_skipped_providers_not_probed_again(env, monkeypatch):
    providers = [{"id": "p_bad", "name": "Bad", "type": "openai"}]

    async def fake_get_all(table, *_):
        return providers if table == "llm_providers" else []

    probe_calls: list[str] = []

    async def fake_probe(self, p):
        probe_calls.append(p["id"])
        return {
            "provider_id": p["id"], "name": p["name"], "type": p["type"],
            "display": "unavailable", "value": None, "raw": None,
        }

    monkeypatch.setattr("services.llm_svc.crud.get_all", fake_get_all)
    monkeypatch.setattr(
        "services.llm_svc.LlmService._probe_provider_quota", fake_probe,
    )

    # First call probes once → fail → skip set populated.
    await env.get_quota()
    assert probe_calls == ["p_bad"]

    # Bypass the 30s cache so the loop re-runs but the skip set kicks in.
    env._quota_cache = None
    env._quota_cache_at = 0.0

    # Second call must NOT probe again. Result still contains the
    # provider with display=unavailable + the "stuck" raw hint.
    out = await env.get_quota()
    assert probe_calls == ["p_bad"]  # unchanged — no second probe
    assert out[0]["display"] == "unavailable"
    assert "刷新" in (out[0]["raw"] or "")


@pytest.mark.asyncio
async def test_force_refresh_reprobes_and_keeps_failures(env, monkeypatch):
    providers = [{"id": "p_bad", "name": "Bad", "type": "openai"}]

    async def fake_get_all(table, *_):
        return providers if table == "llm_providers" else []

    probe_calls: list[str] = []

    async def fake_probe_fails(self, p):
        probe_calls.append(p["id"])
        return {
            "provider_id": p["id"], "name": p["name"], "type": p["type"],
            "display": "unavailable", "value": None, "raw": None,
        }

    monkeypatch.setattr("services.llm_svc.crud.get_all", fake_get_all)
    monkeypatch.setattr(
        "services.llm_svc.LlmService._probe_provider_quota", fake_probe_fails,
    )

    # First call → fail → in skip set
    await env.get_quota()
    assert env._unavailable_provider_ids == {"p_bad"}

    # User hits "刷新" → force=True → skip set cleared, re-probe runs
    await env.get_quota(force=True)
    assert probe_calls == ["p_bad", "p_bad"]  # second probe happened
    # Still failing → back in the set
    assert env._unavailable_provider_ids == {"p_bad"}


@pytest.mark.asyncio
async def test_force_refresh_recovers_when_provider_starts_working(
    env, monkeypatch,
):
    providers = [{"id": "p_flaky", "name": "Flaky", "type": "openai"}]
    call_count = {"n": 0}

    async def fake_get_all(table, *_):
        return providers if table == "llm_providers" else []

    async def fake_probe(self, p):
        call_count["n"] += 1
        # First call fails, second call succeeds.
        if call_count["n"] == 1:
            display = "unavailable"
        else:
            display = "available"
        return {
            "provider_id": p["id"], "name": p["name"], "type": p["type"],
            "display": display, "value": None, "raw": None,
        }

    monkeypatch.setattr("services.llm_svc.crud.get_all", fake_get_all)
    monkeypatch.setattr(
        "services.llm_svc.LlmService._probe_provider_quota", fake_probe,
    )

    # Boot probe — fails
    await env.get_quota()
    assert env._unavailable_provider_ids == {"p_flaky"}

    # User hits refresh — second probe succeeds → skip set clears
    out = await env.get_quota(force=True)
    assert out[0]["display"] == "available"
    assert env._unavailable_provider_ids == set()
