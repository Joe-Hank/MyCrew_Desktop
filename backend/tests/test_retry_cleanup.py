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
    """Configurable in-memory crud stub.

    Tests populate ``stub.projects`` / ``stub.tasks`` (dict by id) and
    inspect ``stub.update_calls`` afterwards. Default state: no rows,
    no calls — matches the original behaviour so legacy tests that
    only assert ``update_calls`` still work.
    """
    class Stub:
        def __init__(self):
            self.projects: dict[str, dict] = {}
            self.tasks: dict[str, dict] = {}
            self.update_calls: list[tuple[str, str, dict]] = []

        async def update_by_id(self, table, row_id, data):
            self.update_calls.append((table, row_id, dict(data)))
            store = self.projects if table == "projects" else self.tasks
            row = store.get(row_id, {})
            row.update(data)
            store[row_id] = {"id": row_id, **row}
            return store[row_id]

        async def get_by_id(self, table, row_id):
            store = self.projects if table == "projects" else self.tasks
            return store.get(row_id)

        async def get_all(self, table, where=None, params=None):
            if table != "tasks":
                return []
            if where and "project_id" in where and "id !=" in where and params:
                pid, exclude = params[0], params[1]
                return [
                    t for t in self.tasks.values()
                    if t.get("project_id") == pid and t.get("id") != exclude
                ]
            return list(self.tasks.values())

    stub = Stub()
    import services.workflow_svc as ws
    monkeypatch.setattr(ws, "crud", stub)
    return stub


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

    assert stub_crud.update_calls == [("tasks", "t1", {"io_out_ref": None})]


@pytest.mark.asyncio
async def test_cleanup_idempotent_when_dir_missing(patched_output_dir, stub_crud):
    """First-run retry (no previous artifacts) must not raise."""
    from services.workflow_svc import WorkflowService

    svc = WorkflowService()
    # Doesn't raise.
    await svc._cleanup_task_artifacts("p1", "nonexistent_task")
    # DB pointer still cleared — harmless if it was already null.
    assert stub_crud.update_calls == [("tasks", "nonexistent_task", {"io_out_ref": None})]


# ── Stage C (2026-05-19): project-side artifact cleanup ─────────────


def _seed_project_root(tmp_path, files_to_create=None):
    """Build a project root tree, optionally pre-populated with files."""
    project_root = tmp_path / "project_root"
    project_root.mkdir()
    for rel in files_to_create or []:
        f = project_root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("// stale content", encoding="utf-8")
    return project_root


@pytest.mark.asyncio
async def test_cleanup_deletes_task_output_paths(patched_output_dir, stub_crud):
    """Real artifact files at task.output_paths under project_root must
    be wiped on retry. Without this, the stale .cs/.png/.wav satisfies
    emit_output's file-exists check and silently lies about 'success'
    on the next run (the stale-state trap, 2026-05-19 incident)."""
    from services.workflow_svc import WorkflowService

    project_root = _seed_project_root(
        patched_output_dir,
        files_to_create=[
            "Assets/Scripts/GameManager.cs",
            "Assets/Scripts/GameManager.cs.meta",
            "Assets/Sprites/coin.png",
            "Assets/Sprites/coin.png.meta",
        ],
    )
    stub_crud.projects["p1"] = {"id": "p1", "root_path": str(project_root)}
    stub_crud.tasks["t1"] = {
        "id": "t1", "project_id": "p1",
        "output_paths": '["Assets/Scripts/GameManager.cs", "Assets/Sprites/coin.png"]',
    }
    _seed_task_dir(patched_output_dir, "p1", "t1")

    await WorkflowService()._cleanup_task_artifacts("p1", "t1")

    assert not (project_root / "Assets/Scripts/GameManager.cs").exists()
    assert not (project_root / "Assets/Scripts/GameManager.cs.meta").exists()
    assert not (project_root / "Assets/Sprites/coin.png").exists()
    assert not (project_root / "Assets/Sprites/coin.png.meta").exists()


@pytest.mark.asyncio
async def test_cleanup_skips_paths_shared_with_other_tasks(
    patched_output_dir, stub_crud,
):
    """If another task in the same project lists the same output path,
    leave it alone — the other task still owns it."""
    from services.workflow_svc import WorkflowService

    project_root = _seed_project_root(
        patched_output_dir,
        files_to_create=[
            "Assets/Scripts/Shared.cs",  # shared between t1 and t2
            "Assets/Scripts/MyOwn.cs",   # only t1
        ],
    )
    stub_crud.projects["p1"] = {"id": "p1", "root_path": str(project_root)}
    stub_crud.tasks["t1"] = {
        "id": "t1", "project_id": "p1",
        "output_paths": '["Assets/Scripts/Shared.cs", "Assets/Scripts/MyOwn.cs"]',
    }
    stub_crud.tasks["t2"] = {
        "id": "t2", "project_id": "p1",
        "output_paths": '["Assets/Scripts/Shared.cs"]',
    }

    await WorkflowService()._cleanup_task_artifacts("p1", "t1")

    assert (project_root / "Assets/Scripts/Shared.cs").exists(), \
        "shared file MUST survive — t2 still owns it"
    assert not (project_root / "Assets/Scripts/MyOwn.cs").exists(), \
        "task-only file should be wiped"


@pytest.mark.asyncio
async def test_cleanup_path_escape_guard(patched_output_dir, stub_crud, tmp_path):
    """An output_path like `../escape.txt` must NOT escape project_root.
    Path resolution is rejected; the outside file stays put."""
    from services.workflow_svc import WorkflowService

    project_root = _seed_project_root(patched_output_dir)
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("not yours to touch", encoding="utf-8")

    stub_crud.projects["p1"] = {"id": "p1", "root_path": str(project_root)}
    stub_crud.tasks["t1"] = {
        "id": "t1", "project_id": "p1",
        "output_paths": '["../outside_secret.txt"]',
    }

    await WorkflowService()._cleanup_task_artifacts("p1", "t1")

    assert outside.exists(), "path escape attempt must not delete outside files"


@pytest.mark.asyncio
async def test_cleanup_no_root_path_skips_project_side(
    patched_output_dir, stub_crud,
):
    """If the project hasn't bound a root_path yet (PM phase, pre-clone),
    project-side cleanup is a no-op — there's nothing on disk to clean."""
    from services.workflow_svc import WorkflowService

    stub_crud.projects["p1"] = {"id": "p1", "root_path": None}
    stub_crud.tasks["t1"] = {
        "id": "t1", "project_id": "p1",
        "output_paths": '["Assets/Scripts/Foo.cs"]',
    }

    # Should not raise.
    await WorkflowService()._cleanup_task_artifacts("p1", "t1")


@pytest.mark.asyncio
async def test_cleanup_empty_output_paths(patched_output_dir, stub_crud):
    """Task with no output_paths (legacy PM data or kind=final_qa):
    project-side pass is a no-op."""
    from services.workflow_svc import WorkflowService

    project_root = _seed_project_root(patched_output_dir)
    stub_crud.projects["p1"] = {"id": "p1", "root_path": str(project_root)}
    stub_crud.tasks["t1"] = {
        "id": "t1", "project_id": "p1",
        "output_paths": "[]",
    }

    await WorkflowService()._cleanup_task_artifacts("p1", "t1")


@pytest.mark.asyncio
async def test_cleanup_meta_optional(patched_output_dir, stub_crud):
    """Non-Unity files (e.g. .wav) don't have .meta — cleanup should
    skip the missing .meta sibling silently, not crash."""
    from services.workflow_svc import WorkflowService

    project_root = _seed_project_root(
        patched_output_dir,
        files_to_create=["Assets/Audio/jump.wav"],  # no .meta sibling
    )
    stub_crud.projects["p1"] = {"id": "p1", "root_path": str(project_root)}
    stub_crud.tasks["t1"] = {
        "id": "t1", "project_id": "p1",
        "output_paths": '["Assets/Audio/jump.wav"]',
    }

    await WorkflowService()._cleanup_task_artifacts("p1", "t1")

    assert not (project_root / "Assets/Audio/jump.wav").exists()
