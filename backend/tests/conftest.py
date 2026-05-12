"""Shared fixtures for backend tests — mock CRUD, event bus, LLM gateway."""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.events import DomainEvent
from domain.harness.states import ProjectState, TaskState


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
