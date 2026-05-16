"""Smoke test for project_svc.create_project_with_tasks rollback path.

Audit (2026-05-16 architecture-audit.md, Top 5 #4) flagged that mid-loop
exception left orphan project + partial tasks in DB. The compensating
transaction model now calls delete_project on any failure during the
two-pass insert.
"""
from __future__ import annotations

import pytest

import services.project_svc as project_svc_mod
from services.project_svc import ProjectService


@pytest.mark.asyncio
async def test_create_project_rolls_back_on_task_insert_failure(fake_crud, monkeypatch):
    monkeypatch.setattr(project_svc_mod, "crud", fake_crud)

    svc = ProjectService()
    call_count = {"n": 0}
    original_insert = fake_crud.insert

    async def maybe_failing_insert(table: str, data: dict, id_prefix: str = ""):
        if table == "tasks":
            call_count["n"] += 1
            # Fail on the 3rd task insert
            if call_count["n"] == 3:
                raise RuntimeError("simulated DB write failure")
        return await original_insert(table, data, id_prefix=id_prefix)

    fake_crud.insert = maybe_failing_insert  # type: ignore[method-assign]

    tasks = [
        {"title": "t1", "deps": []},
        {"title": "t2", "deps": [0]},
        {"title": "t3", "deps": [0]},  # fails here
        {"title": "t4", "deps": [1, 2]},
    ]

    with pytest.raises(RuntimeError, match="simulated DB write failure"):
        await svc.create_project_with_tasks(
            {"name": "test"}, tasks,
        )

    # Compensating delete should have cleared the project + its tasks.
    projects_left = await fake_crud.get_all("projects")
    tasks_left = await fake_crud.get_all("tasks")
    assert projects_left == [], (
        "rollback should remove the half-created project; "
        f"got: {projects_left}"
    )
    assert tasks_left == [], (
        "rollback should remove every task that was inserted before failure; "
        f"got: {tasks_left}"
    )


@pytest.mark.asyncio
async def test_create_project_happy_path_persists(fake_crud, monkeypatch):
    monkeypatch.setattr(project_svc_mod, "crud", fake_crud)
    svc = ProjectService()

    tasks = [
        {"title": "t1", "deps": []},
        {"title": "t2", "deps": [0]},
    ]
    result = await svc.create_project_with_tasks({"name": "test"}, tasks)
    assert result is not None
    assert result["name"] == "test"
    persisted_tasks = await fake_crud.get_all("tasks")
    assert len(persisted_tasks) == 2
