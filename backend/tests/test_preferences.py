"""Stage-A smoke tests: user_preferences KV + dismissible-dialog wiring.

Runs against a real on-disk SQLite (in tmp_path) because preferences_svc
uses raw `db.execute` upserts that FakeCRUD doesn't model. The fixture
boots `bootstrap.app.create_app` to apply migration 0014 and re-bind
sqlite_repo to the temp DB path before each test.
"""
from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    """Point DB_PATH at a temp file, run migrations, return path."""
    db_file = tmp_path / "test.db"

    # Patch the resolved DB path used by sqlite_repo + alembic helpers.
    import bootstrap.paths as paths_mod
    monkeypatch.setattr(paths_mod, "DB_PATH", db_file)
    import infra.repo.sqlite_repo as sqlite_repo
    monkeypatch.setattr(sqlite_repo, "DB_PATH", db_file)
    monkeypatch.setattr(sqlite_repo, "_db", None)

    # Run migrations against the new DB and open a connection.
    await sqlite_repo.init_db()
    yield db_file
    await sqlite_repo.close_db()


@pytest.mark.asyncio
async def test_set_and_get_roundtrip(fresh_db):
    from services import preferences_svc

    await preferences_svc.set_value("foo", {"bar": 42})
    all_prefs = await preferences_svc.get_all()
    assert all_prefs == {"foo": {"bar": 42}}


@pytest.mark.asyncio
async def test_update_overwrites_existing(fresh_db):
    from services import preferences_svc

    await preferences_svc.set_value("foo", "v1")
    await preferences_svc.set_value("foo", "v2")
    all_prefs = await preferences_svc.get_all()
    assert all_prefs == {"foo": "v2"}


@pytest.mark.asyncio
async def test_dismissed_dialog_namespacing(fresh_db):
    from services import preferences_svc

    await preferences_svc.set_dismissed_dialog(
        "retry.cleanup_artifacts", "cleanup",
    )
    all_prefs = await preferences_svc.get_all()
    key = preferences_svc.dismissed_dialog_key("retry.cleanup_artifacts")
    assert key in all_prefs
    val = all_prefs[key]
    assert val["choice"] == "cleanup"
    assert "dismissed_at" in val


@pytest.mark.asyncio
async def test_delete_removes_row(fresh_db):
    from services import preferences_svc

    await preferences_svc.set_value("foo", "v1")
    removed = await preferences_svc.delete_value("foo")
    assert removed is True
    assert await preferences_svc.get_all() == {}

    # Idempotent — deleting again returns False but doesn't raise.
    assert await preferences_svc.delete_value("foo") is False


@pytest.mark.asyncio
async def test_empty_key_rejected(fresh_db):
    from services import preferences_svc

    with pytest.raises(ValueError):
        await preferences_svc.set_value("", "anything")
    with pytest.raises(ValueError):
        await preferences_svc.set_value("   ", "anything")
