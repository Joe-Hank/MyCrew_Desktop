"""Stage-F smoke tests: _StreamingAssistantMessage throttled-flush flow.

Verifies:
  - start() reserves an empty row
  - note() flushes at most ~1Hz
  - finalise() writes the final text
  - abort() drops the reserved row (no orphan partial)
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    """Real SQLite via the same fixture shape as test_preferences."""
    db_file = tmp_path / "test.db"
    import bootstrap.paths as paths_mod
    monkeypatch.setattr(paths_mod, "DB_PATH", db_file)
    import infra.repo.sqlite_repo as sqlite_repo
    monkeypatch.setattr(sqlite_repo, "DB_PATH", db_file)
    monkeypatch.setattr(sqlite_repo, "_db", None)

    # We need at least the inception_sessions parent row before inserting
    # a message because of the FK (sqlite enforces with PRAGMA on).
    await sqlite_repo.init_db()
    from infra.repo import crud
    await crud.insert("inception_sessions", {
        "id": "s_test",
        "title": "test",
    })
    yield db_file
    await sqlite_repo.close_db()


@pytest.mark.asyncio
async def test_start_reserves_empty_row(fresh_db):
    from services.inception_svc import _StreamingAssistantMessage
    from infra.repo import crud

    writer = _StreamingAssistantMessage("s_test")
    await writer.start()
    row = await crud.get_by_id("inception_messages", writer.message_id)
    assert row is not None
    assert row["content"] == ""
    assert row["role"] == "assistant"


@pytest.mark.asyncio
async def test_finalise_writes_full_text(fresh_db):
    from services.inception_svc import _StreamingAssistantMessage
    from infra.repo import crud

    writer = _StreamingAssistantMessage("s_test")
    await writer.start()
    await writer.finalise("complete response")

    row = await crud.get_by_id("inception_messages", writer.message_id)
    assert row["content"] == "complete response"


@pytest.mark.asyncio
async def test_note_throttles_writes(fresh_db, monkeypatch):
    """Two note() calls < 1s apart only flush once."""
    import services.inception_svc as inception_svc
    from infra.repo import crud

    # Freeze monotonic so we can step it precisely.
    clock = {"t": 1000.0}
    monkeypatch.setattr(inception_svc.time, "monotonic", lambda: clock["t"])

    writer = inception_svc._StreamingAssistantMessage("s_test")
    await writer.start()

    # First note flushes (no prior flush ts).
    await writer.note("v1")
    assert (await crud.get_by_id("inception_messages", writer.message_id))["content"] == "v1"

    # Second note 0.5s later — within throttle window, must NOT flush.
    clock["t"] += 0.5
    await writer.note("v1 plus")
    assert (await crud.get_by_id("inception_messages", writer.message_id))["content"] == "v1"

    # Third note 1.1s after the original flush — past window, must flush.
    clock["t"] += 0.7  # cumulative +1.2s
    await writer.note("v1 plus tail")
    assert (
        await crud.get_by_id("inception_messages", writer.message_id)
    )["content"] == "v1 plus tail"


@pytest.mark.asyncio
async def test_abort_removes_row(fresh_db):
    from services.inception_svc import _StreamingAssistantMessage
    from infra.repo import crud

    writer = _StreamingAssistantMessage("s_test")
    await writer.start()
    await writer.note("partial")  # any content
    await writer.abort()

    row = await crud.get_by_id("inception_messages", writer.message_id)
    assert row is None, "abort() must remove the reserved row"


@pytest.mark.asyncio
async def test_finalise_without_start_inserts_fresh(fresh_db):
    """If the caller never streamed, finalise() still produces one row."""
    from services.inception_svc import _StreamingAssistantMessage
    from infra.repo import crud

    writer = _StreamingAssistantMessage("s_test")
    # Skip start(); jump straight to finalise.
    await writer.finalise("oneshot")

    row = await crud.get_by_id("inception_messages", writer.message_id)
    assert row is not None
    assert row["content"] == "oneshot"
