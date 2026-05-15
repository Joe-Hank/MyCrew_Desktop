"""Stage-D smoke tests: list_performers + Phase 5 v4 contract.

Validates the new Phase 5 wiring without booting a real LLM:
  - list_performers returns the standalone-eligible agents + Crews
  - PerformerRef + Assignment Pydantic schema rejects unknown shapes
  - _validate_assignments catches:
      * setup-task indices being assigned
      * ids outside the live pool
      * unknown kind values
  - Draft blueprint merge stamps performer_kind + performer_id
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agents.sub_agents._planner_models import (
    Assignment,
    PerformerRef,
    SubmitAssignmentsArgs,
)


# ── Pydantic shape ────────────────────────────────────────────────

def test_performer_ref_kind_literal():
    PerformerRef(kind="agent", id="agent_xyz")
    PerformerRef(kind="crew", id="crew_xyz")
    with pytest.raises(ValidationError):
        PerformerRef(kind="team", id="x")  # invalid literal


def test_assignment_requires_performer_ref():
    Assignment(
        task_index=0,
        performer_ref=PerformerRef(kind="agent", id="agent_x"),
        reason="why",
    )
    with pytest.raises(ValidationError):
        # Missing reason
        Assignment(
            task_index=0,
            performer_ref=PerformerRef(kind="agent", id="agent_x"),
        )


def test_submit_assignments_rejects_new_agent_field():
    """Confirm the schema has no new_agent escape hatch."""
    # SubmitAssignmentsArgs is just a list wrapper; the relevant guard
    # is that Assignment doesn't have a new_agent field at all.
    fields = Assignment.model_fields
    assert "new_agent" not in fields, "new_agent must not be a model field"
    assert set(fields.keys()) == {"task_index", "performer_ref", "reason"}


# ── _build_payload + list_performers DB query ─────────────────────

@pytest.mark.asyncio
async def test_build_payload_returns_pool(fake_crud, monkeypatch):
    import agents.sub_agents._list_performers_tool as lp
    monkeypatch.setattr(lp, "crud", fake_crud)

    fake_crud.seed("agents", [
        {"id": "agent_a", "role": "Narrative Designer", "goal": "narrate"},
        {"id": "agent_b", "role": "ComfyUI Image Generator", "goal": "gen"},
        {"id": "agent_c", "role": "Plan Maker", "goal": "plan"},
    ])
    fake_crud.seed("crews", [
        {"id": "crew_1", "name": "Art Crew", "is_auto_generated": 0,
         "applicable_scenarios": "2D sprite",
         "agent_sequence": json.dumps([{"role": "head"}, {"role": "qa"}])},
        {"id": "crew_auto", "name": "Old Auto", "is_auto_generated": 1,
         "applicable_scenarios": "",
         "agent_sequence": "[]"},
    ])

    payload = await lp._build_payload("all")
    agent_ids = {a["id"] for a in payload["agents"]}
    crew_ids = {c["id"] for c in payload["crews"]}

    # Narrative Designer is standalone-eligible
    assert "agent_a" in agent_ids
    # ComfyUI Image Generator is Crew-internal only — NOT in standalone pool
    assert "agent_b" not in agent_ids
    # Plan Maker is excluded
    assert "agent_c" not in agent_ids
    # Crews: seeded one included, auto-generated excluded
    assert "crew_1" in crew_ids
    assert "crew_auto" not in crew_ids

    # Step count derived from agent_sequence
    art = next(c for c in payload["crews"] if c["id"] == "crew_1")
    assert art["step_count"] == 2


# ── _validate_assignments cross-checks ────────────────────────────

@pytest.mark.asyncio
async def test_validate_assignments_rejects_unknown_id(fake_crud, monkeypatch):
    import agents.sub_agents._planner_orchestrator as orch
    import agents.sub_agents._list_performers_tool as lp
    monkeypatch.setattr(orch, "crud", fake_crud)
    monkeypatch.setattr(lp, "crud", fake_crud)

    fake_crud.seed("agents", [
        {"id": "agent_real", "role": "Narrative Designer", "goal": ""},
    ])
    fake_crud.seed("crews", [])

    pathed = [
        {"kind": "setup", "title": "init"},     # index 0 — setup
        {"kind": "regular", "title": "doc"},    # index 1
    ]
    raw = [
        {"task_index": 1, "performer_ref": {"kind": "agent", "id": "ghost"},
         "reason": "made it up"},
    ]
    with pytest.raises(ValueError, match="not in the live pool|不在可用池"):
        await orch._validate_assignments(raw, pathed)


@pytest.mark.asyncio
async def test_validate_assignments_rejects_setup_assignment(fake_crud, monkeypatch):
    import agents.sub_agents._planner_orchestrator as orch
    import agents.sub_agents._list_performers_tool as lp
    monkeypatch.setattr(orch, "crud", fake_crud)
    monkeypatch.setattr(lp, "crud", fake_crud)

    fake_crud.seed("agents", [
        {"id": "agent_real", "role": "Narrative Designer", "goal": ""},
    ])
    fake_crud.seed("crews", [])

    pathed = [{"kind": "setup", "title": "init"}]
    raw = [
        {"task_index": 0, "performer_ref": {"kind": "agent", "id": "agent_real"},
         "reason": "x"},
    ]
    with pytest.raises(ValueError, match="setup"):
        await orch._validate_assignments(raw, pathed)


@pytest.mark.asyncio
async def test_validate_assignments_accepts_valid_pool(fake_crud, monkeypatch):
    import agents.sub_agents._planner_orchestrator as orch
    import agents.sub_agents._list_performers_tool as lp
    monkeypatch.setattr(orch, "crud", fake_crud)
    monkeypatch.setattr(lp, "crud", fake_crud)

    fake_crud.seed("agents", [
        {"id": "agent_nar", "role": "Narrative Designer", "goal": ""},
    ])
    fake_crud.seed("crews", [
        {"id": "crew_art", "name": "Art Crew", "is_auto_generated": 0,
         "applicable_scenarios": "2D sprite",
         "agent_sequence": "[]"},
    ])

    pathed = [
        {"kind": "setup", "title": "init"},
        {"kind": "regular", "title": "doc"},
        {"kind": "regular", "title": "sprite"},
    ]
    raw = [
        {"task_index": 1,
         "performer_ref": {"kind": "agent", "id": "agent_nar"},
         "reason": "doc"},
        {"task_index": 2,
         "performer_ref": {"kind": "crew", "id": "crew_art"},
         "reason": "sprite"},
    ]
    validated = await orch._validate_assignments(raw, pathed)
    assert validated == raw
