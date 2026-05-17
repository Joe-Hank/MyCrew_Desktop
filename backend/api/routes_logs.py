"""GET /logs — surface the structlog tap's in-memory ring buffer.

T1.2 of the 2026-05-17 LogDrawer enhancement plan. Companion to
`infra/log_pipeline.tap_processor` which feeds the buffer on every
backend log line. LogDrawer mount-time replay queries this so opening
the panel after a refresh / new session shows the most recent N
entries instead of an empty pane.

Query params:
  level    debug | info | warning | warn | error (warning|warn alias)
  source   matches the top-level prefix of event name (mcp / workflow /
           pm / llm / startup / ...). Single value; for OR-of-multiple
           let the frontend post-filter.
  since    ISO timestamp; only entries with ts >= since
  q        free-text — substring match against event name + project_id
           + task_id (case-insensitive). Cheap LIKE-style.
  limit    1..5000, default 500.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from services.log_svc import log_svc

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("")
async def list_logs(
    level: str | None = Query(None),
    source: str | None = Query(None),
    since: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Read the in-memory ring buffer. Filters are AND-ed.

    The buffer is bounded (2000 records by `MAX_BUFFER` in log_svc), so
    queries are O(buffer_size) and stay sub-millisecond even with the
    default 500 limit. We don't hit SQLite — the tap_processor wrote
    to file + buffer, not to SQLite (intentional: the legacy `logs`
    table was a sparse audit channel; live LogDrawer reads from buffer
    instead so noisy debug-level entries don't bloat the DB).
    """
    # Snapshot the buffer (cheap copy) so iteration doesn't fight with
    # concurrent appends from the structlog tap thread.
    rows = list(log_svc._buffer)

    if level:
        # warning / warn synonym — structlog emits "warning" but users
        # type "warn" everywhere.
        wanted = "warning" if level.lower() in ("warn", "warning") else level.lower()
        rows = [r for r in rows if str(r.get("level", "")).lower() == wanted]
    if source:
        rows = [r for r in rows if r.get("source") == source]
    if since:
        rows = [r for r in rows if str(r.get("ts", "")) >= since]
    if q:
        needle = q.lower()
        rows = [
            r for r in rows
            if needle in str(r.get("event", "")).lower()
            or needle in str(r.get("project_id") or "").lower()
            or needle in str(r.get("task_id") or "").lower()
            or needle in str(r.get("fields", {})).lower()
        ]

    # Caller wants newest-first. Buffer is append-order (oldest first),
    # so reverse then slice.
    rows.reverse()
    rows = rows[:limit]
    return {"ok": True, "data": {"logs": rows, "buffer_size": len(log_svc._buffer)}}


@router.get("/sources")
async def list_sources():
    """Return the distinct `source` prefixes currently seen in the
    buffer — drives the source filter dropdown in the LogDrawer
    (alphabetical, plus 'app' as a catch-all). Cheap O(buffer)."""
    seen: set[str] = set()
    for r in log_svc._buffer:
        s = r.get("source")
        if isinstance(s, str) and s:
            seen.add(s)
    return {"ok": True, "data": {"sources": sorted(seen)}}
