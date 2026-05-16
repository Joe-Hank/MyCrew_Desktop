"""Stage-B smoke tests: retry_task artifact cleanup.

Verifies workflow_svc._cleanup_task_artifacts wipes the right paths and
keeps the rest. We isolate the cleanup method itself — the broader
retry_task flow already has coverage in test_workflow_svc.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def patched_output_dir(tmp_path, monkeypatch):
    import bootstrap.paths as paths_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)
    # workflow_svc imports OUTPUT_DIR lazily inside the cleanup method,
    # so patching the module is enough — no re-import needed.
    return tmp_path


@pytest.fixture
def stub_crud(monkeypatch):
    """Capture update_by_id calls so we can assert the IO ref is cleared."""
    calls: list[tuple[str, str, dict]] = []

    class Stub:
        async def update_by_id(self, table, row_id, data):
            calls.append((table, row_id, dict(data)))
            return {"id": row_id, **data}

        async def get_by_id(self, *a, **kw):
            return None

    import services.workflow_svc as ws
    monkeypatch.setattr(ws, "crud", Stub())
    return calls


def _seed_task_dir(root: Path, project_id: str, task_id: str) -> Path:
    task_dir = root / project_id / task_id
    sub_dir = task_dir / "sub"
    sub_dir.mkdir(parents=True)
    (sub_dir / "0_head_out.json").write_text("{}", encoding="utf-8")
    (sub_dir / "0_head_out.md").write_text("# old", encoding="utf-8")
    (task_dir / "out.json").write_text("{}", encoding="utf-8")
    (task_dir / "out.md").write_text("# old", encoding="utf-8")
    (task_dir / "in.json").write_text("{}", encoding="utf-8")
    (task_dir / "in.md").write_text("# input", encoding="utf-8")
    return task_dir


@pytest.mark.asyncio
async def test_cleanup_removes_sub_dir_and_outputs(patched_output_dir, stub_crud):
    from services.workflow_svc import WorkflowService

    task_dir = _seed_task_dir(patched_output_dir, "p1", "t1")
    svc = WorkflowService()

    await svc._cleanup_task_artifacts("p1", "t1")

    assert not (task_dir / "sub").exists(), "sub/ should be wiped"
    assert not (task_dir / "out.json").exists(), "out.json should be wiped"
    assert not (task_dir / "out.md").exists(), "out.md should be wiped"
    # Inputs survive — they describe the task itself.
    assert (task_dir / "in.json").exists(), "in.json must survive"
    assert (task_dir / "in.md").exists(), "in.md must survive"


@pytest.mark.asyncio
async def test_cleanup_clears_io_out_ref(patched_output_dir, stub_crud):
    from services.workflow_svc import WorkflowService

    _seed_task_dir(patched_output_dir, "p1", "t1")
    svc = WorkflowService()

    await svc._cleanup_task_artifacts("p1", "t1")

    assert stub_crud == [("tasks", "t1", {"io_out_ref": None})]


@pytest.mark.asyncio
async def test_cleanup_idempotent_when_dir_missing(patched_output_dir, stub_crud):
    """First-run retry (no previous artifacts) must not raise."""
    from services.workflow_svc import WorkflowService

    svc = WorkflowService()
    # Doesn't raise.
    await svc._cleanup_task_artifacts("p1", "nonexistent_task")
    # DB pointer still cleared — harmless if it was already null.
    assert stub_crud == [("tasks", "nonexistent_task", {"io_out_ref": None})]
