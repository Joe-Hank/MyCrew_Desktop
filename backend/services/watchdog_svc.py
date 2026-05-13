"""Stall detection watchdog.

Background task that scans every is_running=1 project every 60s. For each
task in TaskState.RUNNING, if `last_activity_at` is older than
`stall_timeout_minutes` (default 20), the task is moved to STALLED via
harness. If every running task in a project goes stalled, the project
moves to STALLED too.

Why this exists: 心之回廊 audit (2026-05-13) found that a hung LLM call or
a wedged MCP server leaves the project state stuck on `running` forever —
no user feedback, no auto-pause. Users can't tell "still working" from
"dead". The shipping default of 20 min covers most legit slow steps while
catching genuine deadlocks reasonably fast.

Started from `bootstrap/app.py` lifespan; cancelled at shutdown.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from infra.repo import crud

log = structlog.get_logger()

# Scan cadence — watchdog ticks every SCAN_INTERVAL_SECONDS. Independent of
# the stall threshold itself (which is a user-configurable setting).
SCAN_INTERVAL_SECONDS = 60


async def _get_stall_timeout_minutes() -> int:
    """Read `stall_timeout_minutes` from app_settings; fall back to 20."""
    rows = await crud.get_all(
        "app_settings", "key = ?", ("stall_timeout_minutes",),
    )
    if rows:
        try:
            return int(rows[0]["value"])
        except (TypeError, ValueError):
            pass
    return 20


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Python's fromisoformat handles "+00:00" but not "Z" prior to 3.11;
        # we use 3.13 so it's fine. Defensive on tz: assume UTC if naive.
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


async def _check_one_project(project_id: str, stall_seconds: int) -> None:
    """Scan a single project's running tasks; stall any that are over budget."""
    # Lazy-import workflow_svc to avoid circular at module load
    from services.workflow_svc import workflow_svc

    harness = workflow_svc._active.get(project_id)
    if harness is None:
        # Project was completed/aborted since the last scan — nothing to do.
        return

    tasks = await crud.get_all("tasks", "project_id = ? AND status = ?",
                                (project_id, "running"))
    if not tasks:
        return

    now = datetime.now(timezone.utc)
    stalled_any = False
    for t in tasks:
        last = _parse_iso(t.get("last_activity_at")) or _parse_iso(t.get("started_at"))
        if last is None:
            continue  # never had activity — let it through, started_at may not be set yet
        elapsed = (now - last).total_seconds()
        if elapsed < stall_seconds:
            continue

        log.warning("watchdog.task_stalled",
                    project_id=project_id, task_id=t["id"],
                    elapsed_minutes=int(elapsed / 60))
        try:
            events = harness.stall_task(t["id"])
        except Exception as exc:
            log.error("watchdog.stall_task_failed",
                      task_id=t["id"], error=str(exc))
            continue
        await workflow_svc._persist_task_state(project_id, t["id"], harness)
        await workflow_svc._persist_project_state(project_id, harness)
        from infra.event_bus import event_bus
        await event_bus.publish_all(events)
        stalled_any = True

    if stalled_any:
        # Cancel the asyncio task running this stalled task so we don't leak
        # the future. workflow_svc tracks these by key.
        for t in tasks:
            key = f"{project_id}:{t['id']}"
            fut = workflow_svc._run_tasks.get(key)
            if fut and not fut.done():
                fut.cancel()


async def _scan_once() -> None:
    """One sweep over every running project."""
    stall_minutes = await _get_stall_timeout_minutes()
    stall_seconds = stall_minutes * 60

    projects = await crud.get_all("projects", "is_running = ?", (1,))
    if not projects:
        return

    log.debug("watchdog.scan", project_count=len(projects),
              timeout_minutes=stall_minutes)
    for p in projects:
        try:
            await _check_one_project(p["id"], stall_seconds)
        except Exception as exc:
            log.error("watchdog.project_scan_failed",
                      project_id=p["id"], error=str(exc))


async def run_watchdog() -> None:
    """Forever-loop. Cancelled by lifespan shutdown."""
    log.info("watchdog.started", interval_seconds=SCAN_INTERVAL_SECONDS)
    try:
        while True:
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)
            try:
                await _scan_once()
            except Exception as exc:
                log.error("watchdog.scan_failed", error=str(exc))
    except asyncio.CancelledError:
        log.info("watchdog.stopped")
        raise
