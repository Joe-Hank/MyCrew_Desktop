"""Shared fixtures for backend tests — mock CRUD, event bus, LLM gateway."""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import threading
import uuid
from collections import defaultdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.events import DomainEvent
from domain.harness.states import ProjectState, TaskState
from infra import runtime as _infra_runtime


# ── Hard-cleanup hooks (anti-zombie, 2026-05-16) ─────────────────
#
# Background: every few weeks the pytest run leaves a process holding
# the SQLite DB file open, then the next backend boot hangs on
# "database is locked" during migration. Tracked instances all came
# from the same shape: pytest hangs on Ctrl+C because (a) an aiosqlite
# worker thread is still running, or (b) the session-loop fixture has
# a pending task that prevents loop.stop() from unblocking. Python's
# daemon=True flag does not actually force-kill threads stuck in
# blocking I/O on Windows.
#
# The countermeasures:
#   1. _test_main_loop now actively cancels every pending task before
#      stopping the loop, so .stop() really unwinds.
#   2. Then it closes the aiosqlite singleton (if any test opened one)
#      to release the WAL/SHM file handles.
#   3. An atexit-registered hard exit (os._exit) fires after a short
#      grace period if the interpreter still hasn't shut down — this
#      is the final guarantee that "pytest finished" means "process
#      gone, file unlocked".
#
# Combined with pytest-timeout=30s in pyproject.toml, even a buggy
# test that wedges on an unawaited future can't survive the run.

_HARD_EXIT_GRACE_S = 5.0


def _force_exit_if_still_alive() -> None:
    """Fallback: if the interpreter is still alive _HARD_EXIT_GRACE_S
    seconds after atexit fires, kill the process. Runs in a daemon
    timer so it doesn't itself prevent exit."""
    def _killer():
        os._exit(0)
    t = threading.Timer(_HARD_EXIT_GRACE_S, _killer)
    t.daemon = True
    t.start()


atexit.register(_force_exit_if_still_alive)


async def _drain_pending_tasks(loop: asyncio.AbstractEventLoop) -> None:
    """Cancel every task on the loop except the one running us. Without
    this, loop.stop() can leave the loop's queue with pending callbacks
    that keep the worker thread parked."""
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks(loop) if t is not current]
    for t in pending:
        t.cancel()
    if pending:
        # Brief grace for cancellations to propagate; we don't actually
        # care about results, just that the queue clears.
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture(scope="session", autouse=True)
def _test_main_loop():
    """Session-wide background loop so GuardedLocalTool._guarded_local
    can hop back to a "main loop" in tests just like the FastAPI
    lifespan provides at runtime.

    Teardown is more aggressive than a typical session fixture (see the
    anti-zombie notes at the top of this file): we cancel pending tasks,
    close the aiosqlite singleton, then join the loop thread with a
    bounded timeout. If anything is still wedged after that, the atexit
    hard-exit handler covers the gap.
    """
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _runner():
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=_runner, daemon=True, name="test-main-loop")
    thread.start()
    ready.wait(timeout=5.0)
    _infra_runtime.set_main_loop(loop)
    yield loop

    # 1. Cancel pending tasks on the loop thread.
    try:
        fut = asyncio.run_coroutine_threadsafe(_drain_pending_tasks(loop), loop)
        fut.result(timeout=3.0)
    except Exception:
        pass

    # 2. Close the aiosqlite singleton so its worker thread releases
    #    the DB file. If no test opened one, close_db is a no-op.
    try:
        from infra.repo.sqlite_repo import close_db
        fut = asyncio.run_coroutine_threadsafe(close_db(), loop)
        fut.result(timeout=3.0)
    except Exception:
        pass

    # 3. Stop the loop + join the thread (bounded).
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5.0)


# ── In-memory CRUD mock ──────────────────────────────────────

class FakeCRUD:
    """In-memory CRUD that mimics infra.repo.crud interface."""

    def __init__(self) -> None:
        self._tables: dict[str, dict[str, dict]] = defaultdict(dict)

    def seed(self, table: str, rows: list[dict]) -> None:
        for r in rows:
            self._tables[table][r["id"]] = dict(r)

    async def insert(self, table: str, data: dict, id_prefix: str = "") -> dict:
        row = dict(data)
        if "id" not in row:
            row["id"] = f"{id_prefix}{uuid.uuid4().hex[:12]}"
        self._tables[table][row["id"]] = row
        return row

    async def get_by_id(self, table: str, row_id: str) -> dict | None:
        return self._tables[table].get(row_id)

    async def get_all(self, table: str, where: str = "", params: tuple = ()) -> list[dict]:
        rows = list(self._tables[table].values())
        if not where:
            return rows
        # Simple filter: "key = ?" pattern
        if "= ?" in where:
            col = where.split("=")[0].strip()
            val = params[0] if params else None
            return [r for r in rows if r.get(col) == val]
        return rows

    async def update_by_id(self, table: str, row_id: str, data: dict) -> dict | None:
        row = self._tables[table].get(row_id)
        if not row:
            return None
        row.update(data)
        return row

    async def delete_by_id(self, table: str, row_id: str) -> bool:
        return self._tables[table].pop(row_id, None) is not None

    async def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        rows = await self.get_all(table, where, params)
        return len(rows)

    async def paginate(self, table: str, page: int = 1, size: int = 4,
                       order_by: str = "", where: str = "",
                       params: tuple = ()) -> dict:
        rows = await self.get_all(table, where, params)
        offset = (page - 1) * size
        return {
            "items": rows[offset:offset + size],
            "total": len(rows),
            "page": page,
            "size": size,
        }


# ── Event collector ──────────────────────────────────────────

class FakeEventBus:
    """Collects published events for assertion."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)

    async def publish_all(self, events: list[DomainEvent]) -> None:
        self.events.extend(events)

    def subscribe(self, event_type, handler) -> None:
        pass

    def subscribe_all(self, handler) -> None:
        pass

    def get_events_of_type(self, event_type: type) -> list:
        return [e for e in self.events if isinstance(e, event_type)]

    def clear(self) -> None:
        self.events.clear()


# ── Fake LLM gateway ────────────────────────────────────────

class FakeLlmGateway:
    """Returns canned LLM responses."""

    def __init__(self, default_response: str = "mock response") -> None:
        self.default_response = default_response
        self.call_log: list[dict] = []

    async def chat(self, provider_id, model_name, messages, **kwargs):
        self.call_log.append({
            "provider_id": provider_id,
            "model_name": model_name,
            "messages": messages,
            "kwargs": kwargs,
        })
        from infra.llm.base import LlmResponse, LlmUsage
        return LlmResponse(
            text=self.default_response,
            usage=LlmUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            model=model_name,
        )

    async def check_availability(self, provider_id: str) -> bool:
        return True

    async def shutdown(self) -> None:
        pass


# ── Fake MCP pool ────────────────────────────────────────────

class FakeMCPPool:
    def __init__(self) -> None:
        self._statuses: dict[str, str] = {}

    def get_connection_status(self, server_id: str) -> str:
        return self._statuses.get(server_id, "disconnected")

    async def connect_server(self, server_id: str, config: dict) -> dict:
        self._statuses[server_id] = "connected"
        return {"status": "connected", "tools": []}

    async def disconnect_server(self, server_id: str) -> None:
        self._statuses[server_id] = "disconnected"

    async def restart_server(self, server_id: str) -> dict:
        self._statuses[server_id] = "connected"
        return {"status": "connected"}

    async def remove_server(self, server_id: str) -> None:
        self._statuses.pop(server_id, None)

    async def call(self, server_id: str, tool_name: str, arguments: dict) -> str:
        return json.dumps({"result": "ok"})

    async def start(self, servers: list[dict]) -> None:
        for s in servers:
            self._statuses[s["id"]] = "connected"

    async def stop(self) -> None:
        self._statuses.clear()

    async def refresh_all(self, servers: list[dict]) -> dict:
        return {"connected": len(servers), "failed": 0}

    def get_status_summary(self) -> dict:
        online = sum(1 for s in self._statuses.values() if s == "connected")
        return {"online": online, "offline": len(self._statuses) - online, "servers": {}}

    def set_tools_sync(self, callback) -> None:
        pass


# ── Fake WS manager ─────────────────────────────────────────

class FakeWSManager:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[str, dict]] = []

    async def broadcast(self, event: str, data: dict) -> None:
        self.broadcasts.append((event, data))


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def fake_crud():
    return FakeCRUD()


@pytest.fixture
def fake_event_bus():
    return FakeEventBus()


@pytest.fixture
def fake_llm():
    return FakeLlmGateway()


@pytest.fixture
def fake_mcp_pool():
    return FakeMCPPool()


@pytest.fixture
def fake_ws_manager():
    return FakeWSManager()


def make_task(id: str, deps: list[str] | None = None, **kwargs) -> dict:
    """Helper to build a task dict with defaults."""
    task = {
        "id": id,
        "title": kwargs.get("title", f"Task {id}"),
        "detail": kwargs.get("detail", ""),
        "status": kwargs.get("status", TaskState.PENDING),
        "deps": json.dumps(deps or []),
        "output_schema": json.dumps(kwargs.get("output_schema", {})),
        "agent_id": kwargs.get("agent_id", "agent_1"),
        "kind": kwargs.get("kind", "regular"),
        "project_id": kwargs.get("project_id", "proj_1"),
    }
    return task


def make_project(id: str = "proj_1", **kwargs) -> dict:
    return {
        "id": id,
        "name": kwargs.get("name", "Test Project"),
        "state": kwargs.get("state", "ready"),
        "is_running": kwargs.get("is_running", 0),
        "progress_pct": kwargs.get("progress_pct", 0),
        "execution_kind": kwargs.get("execution_kind", "sequential"),
    }
