"""Cheap unit tests for template_cloner_svc.

The real clone path hits GitHub which we don't want in CI; instead we
build a tiny local bare repo, point TEMPLATE_REPO_URL at it via
monkeypatch, and exercise the full clone + sparse-checkout + rename
sequence."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from services.template_cloner_svc import (
    ScaffoldError,
    TEMPLATE_ID_TO_DIR,
    clone_template,
)


def _make_dummy_repo(tmp_path: Path) -> str:
    """Build a bare repo holding two subdirs that match the real
    template_id_to_dir mapping, so the cloner can target one via
    sparse-checkout."""
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=work, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=work, check=True, capture_output=True)
    # Make one subdir with a sentinel marker matching a real template id
    sub = work / "Universal2D"
    sub.mkdir()
    (sub / "ProjectSettings").mkdir()
    (sub / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2026.1.0f1\n", encoding="utf-8",
    )
    (sub / "README.md").write_text("Universal2D test\n", encoding="utf-8")

    other = work / "Universal3D"
    other.mkdir()
    (other / "README.md").write_text("Universal3D test\n", encoding="utf-8")

    subprocess.run(["git", "add", "-A"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=work, check=True,
                   capture_output=True)

    bare = tmp_path / "templates.git"
    subprocess.run(["git", "clone", "--bare", str(work), str(bare)],
                   check=True, capture_output=True)
    # file:// URL works with git clone --filter on modern git
    return str(bare.as_uri())


@pytest.mark.asyncio
async def test_clone_template_uses_sparse_checkout(tmp_path, monkeypatch):
    repo_url = _make_dummy_repo(tmp_path)
    monkeypatch.setattr(
        "services.template_cloner_svc.TEMPLATE_REPO_URL", repo_url,
    )

    parent = tmp_path / "user-root"
    parent.mkdir()

    target = await clone_template(
        project_id="proj_test",
        template_id="unity_universal_2d",
        parent_dir=str(parent),
        project_slug="PacMan",
    )

    # Target dir lives at <parent>/<slug> after rename
    assert target == parent / "PacMan"
    assert (target / "README.md").exists()
    assert (target / "ProjectSettings" / "ProjectVersion.txt").exists()
    # Sentinel — proves the cloner stamped our marker
    assert (target / ".mycrew_scaffolded").exists()
    # The OTHER template's dir must NOT be present (sparse-checkout
    # filtered it out)
    assert not (target / "../Universal3D").exists()
    # No leftover staging clone in the parent
    leftovers = [p for p in parent.iterdir()
                 if p.name.startswith(".mycrew_clone_")]
    assert leftovers == [], f"staging dir not cleaned: {leftovers}"


@pytest.mark.asyncio
async def test_clone_rejects_chinese_slug(tmp_path):
    parent = tmp_path / "x"
    parent.mkdir()
    with pytest.raises(ScaffoldError, match="不是合法目录名"):
        await clone_template(
            "proj", "unity_universal_2d", str(parent), "中文名",
        )


@pytest.mark.asyncio
async def test_clone_rejects_unknown_template(tmp_path):
    parent = tmp_path / "x"
    parent.mkdir()
    with pytest.raises(ScaffoldError, match="不支持脚手架"):
        await clone_template(
            "proj", "bogus_template", str(parent), "MyProj",
        )


@pytest.mark.asyncio
async def test_clone_progress_hook_called(tmp_path, monkeypatch):
    repo_url = _make_dummy_repo(tmp_path)
    monkeypatch.setattr(
        "services.template_cloner_svc.TEMPLATE_REPO_URL", repo_url,
    )
    parent = tmp_path / "user-root"
    parent.mkdir()

    stages = []
    async def hook(stage, message):
        stages.append((stage, message))

    await clone_template(
        "proj", "unity_universal_2d",
        str(parent), "Foo",
        on_progress=hook,
    )

    # We should at least see git_clone + rename + done events
    stage_names = [s for s, _ in stages]
    assert "git_clone" in stage_names
    assert "rename" in stage_names
    assert "done" in stage_names


def test_mapping_covers_all_template_ids():
    """Catch out-of-sync drift between the cloner mapping and the
    inception template catalog. Every UNITY_TEMPLATES.id should appear
    in TEMPLATE_ID_TO_DIR (so the cloner knows what to fetch)."""
    from data.unity_templates import UNITY_TEMPLATES
    catalog_ids = {
        t["id"] for t in UNITY_TEMPLATES if t.get("kind") == "unity"
    }
    cloner_ids = set(TEMPLATE_ID_TO_DIR.keys())
    missing = catalog_ids - cloner_ids
    assert not missing, (
        f"these Unity template ids exist in the catalog but the cloner "
        f"can't fetch them: {missing}"
    )
