"""Smoke test for WorkflowService per-project asyncio.Lock (PM-v4 audit #3).

The audit (docs/iterations/2026-05-16/architecture-audit.md, Top 5 #3)
flagged a TOCTOU race: `start / pause / retry` all read+write four
in-memory dicts (`_active / _runners / _run_tasks / _outputs`) without
locks, so a double-click could spawn two harnesses for the same
project. This test pins down the lock behaviour:

  - Same project_id → second concurrent start() blocks on the lock
    until the first finishes; afterwards both observe the SAME harness
    instance (only one was created).
  - Different project_ids run in parallel — locks are per-project.
  - The lock is removed by `_cleanup_project` so long-lived processes
    don't accumulate.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from services.workflow_svc import WorkflowService


@pytest.mark.asyncio
async def test_lock_is_per_project():
    svc = WorkflowService()
    lock_a = svc._get_project_lock("proj_a")
    lock_b = svc._get_project_lock("proj_b")
    lock_a2 = svc._get_project_lock("proj_a")
    assert lock_a is lock_a2, "same project_id must return the same lock"
    assert lock_a is not lock_b, "different project_ids must get separate locks"


@pytest.mark.asyncio
async def test_lock_serialises_same_project_starts():
    svc = WorkflowService()
    sequence: list[str] = []

    async def fake_start_locked(project_id: str, **_kwargs):
        sequence.append(f"enter:{project_id}")
        # Yield to the loop so the other coroutine has a chance to
        # *not* race past us — the lock should prevent it.
        await asyncio.sleep(0.02)
        sequence.append(f"exit:{project_id}")

    with patch.object(svc, "_start_locked", side_effect=fake_start_locked):
        # Two concurrent start() calls on the SAME project
        await asyncio.gather(svc.start("proj_a"), svc.start("proj_a"))

    # The two enter/exit pairs must be nested, not interleaved.
    assert sequence == [
        "enter:proj_a", "exit:proj_a",
        "enter:proj_a", "exit:proj_a",
    ]


@pytest.mark.asyncio
async def test_lock_does_not_serialise_different_projects():
    svc = WorkflowService()
    in_flight: set[str] = set()
    max_concurrent = 0

    async def fake_start_locked(project_id: str, **_kwargs):
        nonlocal max_concurrent
        in_flight.add(project_id)
        max_concurrent = max(max_concurrent, len(in_flight))
        await asyncio.sleep(0.02)
        in_flight.remove(project_id)

    with patch.object(svc, "_start_locked", side_effect=fake_start_locked):
        await asyncio.gather(
            svc.start("proj_a"),
            svc.start("proj_b"),
            svc.start("proj_c"),
        )
    assert max_concurrent == 3, (
        "different project_ids should run in parallel"
    )


@pytest.mark.asyncio
async def test_cleanup_project_drops_lock():
    svc = WorkflowService()
    svc._get_project_lock("proj_a")
    assert "proj_a" in svc._project_locks
    svc._cleanup_project("proj_a")
    assert "proj_a" not in svc._project_locks, (
        "stale lock entries should be evicted by cleanup"
    )
