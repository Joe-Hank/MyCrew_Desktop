"""Read-only event-log API for the frontend LogDrawer + future Brain.

Mutation isn't exposed here — events are populated by WsManager.broadcast
and the audit middleware; clients can only query.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from services.events_svc import query_events

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def list_events(
    project_id: str | None = Query(None, description="Filter by project_id"),
    event_type: str | None = Query(None, description="Exact match on event_type"),
    since_ts: str | None = Query(None, description="ISO ts; return events newer than this"),
    limit: int = Query(200, ge=1, le=2000),
) -> dict:
    data = await query_events(
        project_id=project_id,
        event_type=event_type,
        since_ts=since_ts,
        limit=limit,
    )
    return {"ok": True, "data": data}
