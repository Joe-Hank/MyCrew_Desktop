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
    """Scan a single project's running tasks; stall any that are over budget.

    Also detects "orphan-running" — project row says state=running but
    NO task is actually in RUNNING state (typically because an older
    harness bug left the project hanging after the last task failed).
    These get auto-marked STALLED so the UI shows red instead of a
    forever-pulsing blue card.
    """
    # Lazy-import workflow_svc to avoid circular at module load
    from services.workflow_svc import workflow_svc

    harness = workflow_svc._active.get(project_id)

    # Orphan-running detection: no live harness in memory but DB says
    # is_running=1. Means backend was restarted mid-run OR the project
    # was finalized incorrectly. Run a fresh scan and reconcile.
    if harness is None:
        await _reconcile_orphan_project(project_id)
        return

    tasks = await crud.get_all("tasks", "project_id = ? AND status = ?",
                                (project_id, "running"))
    if not tasks:
        # No RUNNING task but harness exists — probably mid-transition
        # or a race; let it self-heal next tick.
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
        # Stamp a friendly reason on the task row so the canvas amber
        # tooltip shows a concrete cause instead of the generic "task
        # execution failed". Mirrors workflow_svc's failure path.
        from infra.repo import crud as _crud
        await _crud.update_by_id("tasks", t["id"], {
            "last_error": f"任务已 {int(elapsed / 60)} 分钟无活动迹象，被监控线程强制停摆。",
            "last_error_kind": "stalled",
        })
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


async def _reconcile_orphan_project(project_id: str) -> None:
    """A project flagged is_running=1 but with no live harness — figure
    out what really happened from task states and update the project row.

    Logic:
      - all tasks terminal      → run finalize (sets COMPLETED* / etc.)
      - some tasks terminal-fail (failed/validation_failed/aborted) but
        none currently RUNNING → STALLED (auto-pause for user attention)
      - some tasks PENDING / BLOCKED, no failures → leave PAUSED so the
        user can manually resume
      - tasks claiming "running" but no harness exists → flip them to
        stalled. Without this, the project stays wedged forever: the
        regular stall scan needs a live harness to call stall_task on,
        and this orphan reconcile used to bail out on any_running=True,
        creating a deadlock. (Surfaced by the 「霓虹攀升」 Anthropic-hang
        incident 2026-05-15.)
    """
    tasks = await crud.get_all("tasks", "project_id = ?", (project_id,))
    if not tasks:
        return

    statuses = [t.get("status") for t in tasks]
    terminal_states = {"done", "failed", "aborted", "validation_failed"}
    fail_states = {"failed", "validation_failed", "aborted"}

    # Force-stall any orphan running tasks. Their asyncio.Task is long
    # dead (backend was restarted or the LLM call hung past TTL), but the
    # DB still says "running" — and the regular stall scan can't help
    # because it needs a live harness to call stall_task.
    orphan_running = [t for t in tasks if t.get("status") == "running"]
    if orphan_running:
        from datetime import datetime, timezone
        from infra.event_bus import event_bus
        from domain.events import TaskFailed
        now_iso = datetime.now(timezone.utc).isoformat()
        for t in orphan_running:
            await crud.update_by_id("tasks", t["id"], {
                "status": "stalled",
                "finished_at": now_iso,
                "last_error": "后端重启或 LLM 调用超时导致任务僵死。watchdog 强制刷为 stalled，点重试可重新调度。",
                "last_error_kind": "stalled",
            })
            log.warning("watchdog.orphan_running_forced_stalled",
                        project_id=project_id, task_id=t["id"])
            # Best-effort domain event so the frontend updates the canvas
            try:
                await event_bus.publish_all([TaskFailed(
                    project_id=project_id, task_id=t["id"],
                    error="orphan running task force-stalled",
                )])
            except Exception:
                pass
        # Re-pull statuses since we just flipped some
        statuses = [
            "stalled" if t.get("status") == "running" else t.get("status")
            for t in tasks
        ]

    all_terminal = all(s in terminal_states for s in statuses)
    any_failed = any(s in fail_states for s in statuses)
    any_running = any(s == "running" for s in statuses)  # now always False

    if any_running:
        return  # never reached after the orphan-running flip above

    if all_terminal:
        # Compute a verdict like _finalize_project would
        from domain.harness.states import ProjectState
        final_qa = next((t for t in tasks if t.get("kind") == "final_qa"), None)
        if final_qa:
            new_state = (
                ProjectState.COMPLETED if final_qa.get("status") == "done"
                else ProjectState.COMPLETED_WITH_ISSUES
            )
        else:
            new_state = (
                ProjectState.COMPLETED_WITH_ISSUES if any_failed
                else ProjectState.COMPLETED
            )
        done_count = sum(1 for s in statuses if s == "done")
        progress = round(done_count / len(tasks) * 100, 1)
        await crud.update_by_id("projects", project_id, {
            "state": new_state,
            "is_running": 0,
            "progress_pct": progress,
        })
        log.info("watchdog.orphan_finalized",
                 project_id=project_id, state=new_state, progress=progress)
        return

    if any_failed:
        await crud.update_by_id("projects", project_id, {
            "state": "stalled",
            "is_running": 0,
        })
        log.warning("watchdog.orphan_stalled", project_id=project_id)
        return

    # Pending tasks but no failures + no live harness — user paused mid-run
    # via backend restart. Move to paused so the UI offers a "resume" path.
    await crud.update_by_id("projects", project_id, {
        "state": "paused",
        "is_running": 0,
    })
    log.info("watchdog.orphan_paused", project_id=project_id)


async def reconcile_all_orphans_on_startup() -> None:
    """Called once from app lifespan after DB init. Sweeps every project
    flagged is_running=1 — they're all orphans by definition because the
    process just started and no harness exists yet."""
    projects = await crud.get_all("projects", "is_running = ?", (1,))
    if not projects:
        return
    log.info("watchdog.startup_reconcile", count=len(projects))
    for p in projects:
        try:
            await _reconcile_orphan_project(p["id"])
        except Exception as exc:
            log.error("watchdog.startup_reconcile_failed",
                      project_id=p["id"], error=str(exc))


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
