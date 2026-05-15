"""Stage-G smoke tests: sub_io endpoint + guidance step_index handling.

End-to-end against the FakeCRUD harness:
  - GET /workflow/tasks/{id}/sub_io?step_index=N reads the right files
  - GET returns nulls (not 404) when the task has no Crew run yet
  - 404 when the task itself doesn't exist
  - task_guidance.chat with step_index reads sub-step files instead of
    the parent task's io_in_ref/io_out_ref
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.task_guidance import _build_context


# ── _build_context with step_index ────────────────────────────────

@pytest.mark.asyncio
async def test_build_context_reads_sub_step_files(tmp_path, monkeypatch):
    import bootstrap.paths as paths_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)

    # Stub crud.get_by_id used inside _build_context for agent lookup
    import agents.task_guidance as tg
    class StubCrud:
        async def get_by_id(self, table, rid):
            if table == "agents" and rid == "agent_x":
                return {"role": "Concept Artist"}
            return None
    monkeypatch.setattr(tg, "crud", StubCrud())

    # Lay down sub-step files for step 2
    sub_dir = tmp_path / "p1" / "tk1" / "sub"
    sub_dir.mkdir(parents=True)
    (sub_dir / "2_executor_in.json").write_text(
        json.dumps({"step_index": 2, "prev_step_payload": {"echo": 1}}),
        encoding="utf-8",
    )
    (sub_dir / "2_executor_out.md").write_text(
        "# Step 3 · executor\n\n## Captured\n\n{\"file_paths\": [\"x.png\"]}",
        encoding="utf-8",
    )

    task = {
        "id": "tk1", "project_id": "p1",
        "title": "Generate sprites", "status": "running",
        "agent_id": "agent_x", "kind": "regular",
    }
    md = await _build_context(task, step_index=2)
    assert "Step 3 · executor" in md or "Step 3" in md
    assert "x.png" in md or "file_paths" in md


@pytest.mark.asyncio
async def test_build_context_without_step_uses_task_io(tmp_path, monkeypatch):
    import agents.task_guidance as tg
    class StubCrud:
        async def get_by_id(self, *_): return None
    monkeypatch.setattr(tg, "crud", StubCrud())

    in_file = tmp_path / "in.json"
    in_file.write_text("plain task input", encoding="utf-8")
    out_md = tmp_path / "out.md"
    out_md.write_text("plain task output md", encoding="utf-8")

    task = {
        "id": "t", "project_id": "p", "title": "t", "status": "done",
        "io_in_ref": str(in_file),
        "io_out_ref": str(tmp_path / "out.json"),
    }
    md = await _build_context(task, step_index=None)
    assert "plain task input" in md
    assert "plain task output md" in md


# ── sub_io endpoint via FastAPI TestClient ────────────────────────

def _make_app(fake_crud, tmp_path, monkeypatch):
    from fastapi import FastAPI
    # Patch crud + paths BEFORE importing routes so they bind to fakes
    import infra.repo.crud as crud_mod
    monkeypatch.setattr(crud_mod, "get_by_id", fake_crud.get_by_id, raising=False)
    monkeypatch.setattr(crud_mod, "update_by_id", fake_crud.update_by_id, raising=False)
    monkeypatch.setattr(crud_mod, "get_all", fake_crud.get_all, raising=False)
    monkeypatch.setattr(crud_mod, "insert", fake_crud.insert, raising=False)
    monkeypatch.setattr(crud_mod, "delete_by_id", fake_crud.delete_by_id, raising=False)
    import bootstrap.paths as paths_mod
    monkeypatch.setattr(paths_mod, "OUTPUT_DIR", tmp_path)

    from api.routes_workflow import router
    app = FastAPI()
    # routes_workflow's APIRouter already declares prefix="/workflow"
    app.include_router(router)
    return app


def test_sub_io_returns_step_files(fake_crud, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    fake_crud.seed("tasks", [{"id": "tkA", "project_id": "pA"}])
    sub_dir = tmp_path / "pA" / "tkA" / "sub"
    sub_dir.mkdir(parents=True)
    (sub_dir / "0_head_in.json").write_text(
        json.dumps({"step_index": 0, "prev_step_payload": None}),
        encoding="utf-8",
    )
    (sub_dir / "0_head_out.json").write_text(
        json.dumps({"step_index": 0, "captured": {"spec": "art"}}),
        encoding="utf-8",
    )
    (sub_dir / "0_head_out.md").write_text("# Step 1 · head\n\nart spec", encoding="utf-8")

    app = _make_app(fake_crud, tmp_path, monkeypatch)
    client = TestClient(app)
    res = client.get("/workflow/tasks/tkA/sub_io?step_index=0")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["step_index"] == 0
    assert data["in"]["step_index"] == 0
    assert data["out"]["captured"] == {"spec": "art"}
    assert "art spec" in (data["raw"] or "")


def test_sub_io_returns_nulls_when_no_sub_dir(fake_crud, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    fake_crud.seed("tasks", [{"id": "tkB", "project_id": "pB"}])
    app = _make_app(fake_crud, tmp_path, monkeypatch)
    client = TestClient(app)
    res = client.get("/workflow/tasks/tkB/sub_io?step_index=0")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data == {"step_index": 0, "in": None, "out": None, "raw": None}


def test_sub_io_404_when_task_missing(fake_crud, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    app = _make_app(fake_crud, tmp_path, monkeypatch)
    client = TestClient(app)
    res = client.get("/workflow/tasks/missing/sub_io?step_index=0")
    assert res.status_code == 404
