"""Event log service — persist + query the universal event stream.

The event stream is the substrate that the future Core AI ("Brain") will
read to understand what's happened in the app. It's populated by two
sources today:

  - `infra.ws.WsManager.broadcast(...)` calls `record_event(...)` before
    fanning out to WebSocket clients. Every UI-visible event lands here.
  - FastAPI middleware in `bootstrap.app` audits POST/PUT/DELETE requests
    as `event_type='api.mutation'` rows.

Auto-truncation runs every 6 hours from `run_event_janitor()`:
  - Global: drop rows older than `EVENT_MAX_AGE_DAYS` (default 30).
  - Per project: keep newest `EVENT_PER_PROJECT_CAP` (default 10000) rows.

Failure on persist is silent (warned to log) — broadcast must NEVER fail
because the event log path failed.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from infra.repo import crud

log = structlog.get_logger()


EVENT_MAX_AGE_DAYS = 30
EVENT_PER_PROJECT_CAP = 10_000
JANITOR_INTERVAL_SECONDS = 6 * 60 * 60   # 6h


async def record_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    actor: str | None = None,
) -> None:
    """Insert one event row. Cheap and fire-and-forget; callers should
    never await something else just to wait on this."""
    payload = payload or {}
    project_id = (
        payload.get("project_id") if isinstance(payload, dict) else None
    )
    task_id = payload.get("task_id") if isinstance(payload, dict) else None
    session_id = (
        payload.get("session_id") if isinstance(payload, dict) else None
    )
    try:
        await crud.insert("events", {
            "id": f"evt_{uuid.uuid4().hex[:12]}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "actor": actor,
            "project_id": project_id if isinstance(project_id, str) else None,
            "task_id": task_id if isinstance(task_id, str) else None,
            "session_id": session_id if isinstance(session_id, str) else None,
            "payload": json.dumps(payload, ensure_ascii=False, default=str),
            "created_at": int(datetime.now(timezone.utc).timestamp()),
        })
    except Exception as exc:  # noqa: BLE001 — must never block broadcast
        log.warning("events.persist_failed", event_type=event_type, error=str(exc))


async def query_events(
    *,
    project_id: str | None = None,
    event_type: str | None = None,
    since_ts: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read events for the LogDrawer / debug / Brain. Newest first."""
    where_parts: list[str] = []
    params: list[Any] = []
    if project_id:
        where_parts.append("project_id = ?")
        params.append(project_id)
    if event_type:
        where_parts.append("event_type = ?")
        params.append(event_type)
    if since_ts:
        where_parts.append("ts > ?")
        params.append(since_ts)
    where_sql = " AND ".join(where_parts) if where_parts else None

    rows = await crud.get_all(
        "events", where_sql, tuple(params) if params else None,
        order_by="ts DESC", limit=limit,
    )
    # Decode payload JSON for caller convenience
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        if item.get("payload"):
            try:
                item["payload"] = json.loads(item["payload"])
            except (json.JSONDecodeError, TypeError):
                pass  # keep raw text on parse fail
        out.append(item)
    return out


async def _cleanup_global_age() -> int:
    """Drop rows older than EVENT_MAX_AGE_DAYS. Returns count removed."""
    cutoff = int(
        datetime.now(timezone.utc).timestamp()
    ) - EVENT_MAX_AGE_DAYS * 86400
    from infra.repo.sqlite_repo import get_db
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM events WHERE created_at < ?", (cutoff,),
    )
    await db.commit()
    return cursor.rowcount or 0


async def _cleanup_per_project_cap() -> int:
    """For each project, keep newest EVENT_PER_PROJECT_CAP rows; drop rest."""
    from infra.repo.sqlite_repo import get_db
    db = await get_db()
    # Find projects with overflow
    cursor = await db.execute(
        "SELECT project_id, COUNT(*) c FROM events "
        "WHERE project_id IS NOT NULL GROUP BY project_id "
        "HAVING c > ?", (EVENT_PER_PROJECT_CAP,),
    )
    rows = await cursor.fetchall()
    total_dropped = 0
    for pid, _count in rows:
        # Keep newest cap rows; delete the rest. Use ts ordering.
        c2 = await db.execute(
            "DELETE FROM events WHERE project_id = ? AND id NOT IN ("
            "  SELECT id FROM events WHERE project_id = ? "
            "  ORDER BY ts DESC LIMIT ?)",
            (pid, pid, EVENT_PER_PROJECT_CAP),
        )
        total_dropped += c2.rowcount or 0
    await db.commit()
    return total_dropped


async def run_event_janitor() -> None:
    """Background loop. Started from app lifespan; cancelled at shutdown."""
    log.info("events.janitor_started",
             interval_hours=JANITOR_INTERVAL_SECONDS / 3600)
    try:
        while True:
            await asyncio.sleep(JANITOR_INTERVAL_SECONDS)
            try:
                aged = await _cleanup_global_age()
                capped = await _cleanup_per_project_cap()
                if aged or capped:
                    log.info("events.cleanup_ran",
                             aged_out=aged, project_cap_out=capped)
            except Exception as exc:  # noqa: BLE001
                log.error("events.cleanup_failed", error=str(exc))
    except asyncio.CancelledError:
        log.info("events.janitor_stopped")
        raise
