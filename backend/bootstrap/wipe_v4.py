"""One-shot PM v4 reset — wipe v3-era projects and stale agents.

User decision (grill Q10, 2026-05-16): the v4 Crew-Native model breaks
enough contracts (performer_kind column, Phase 5 menu, deleted PM/PSM
agents) that supporting in-place migration is more work than just
clearing dev state and re-creating projects. They explicitly accepted
"wipe everything".

This module runs once, guarded by `data/runtime/_v4_reset_done.flag`.
The flag is created after a successful pass; subsequent boots see it
and skip. Deleting the flag re-runs the wipe (useful if v4 lands a
second breaking change).

Order matters:
  1) Backup the DB file to `mycrew.db.pre-v4.<ts>` so a power-user can
     restore old projects out-of-band.
  2) Delete project-scoped state: projects, tasks, inception_sessions,
     audit_events, planner_cache (in-memory; nothing to do).
  3) Delete obsolete agent rows by role name (Project Manager / Project
     Structure Manager / auto-generated Unity workers / standalone
     VFX Artist). Plan Maker is KEPT — inception_svc still tags
     session messages with its role for the chat UI, and the v3
     iterate_existing sub-agent depends on the agents-table filter that
     excludes Plan Maker (Q12: iterate flow unchanged).
"""
from __future__ import annotations

import datetime as dt
import json
import shutil

import structlog

from bootstrap.paths import DB_PATH, RUNTIME_DIR
from infra.repo import crud

log = structlog.get_logger()


_FLAG = RUNTIME_DIR / "_v4_reset_done.flag"


# Agent roles whose rows we purge. Plan Maker stays for the reasons above.
_OBSOLETE_AGENT_ROLES = {
    "Project Manager",
    "Project Structure Manager",
    "项目经理",          # zh alias the bootstrap occasionally used
    "项目结构经理",
}

# Tables wiped of all rows. Order respects FKs (children first, parents last).
_WIPE_TABLES = [
    "task_events",       # depends on tasks
    "task_io",           # depends on tasks
    "tasks",             # depends on projects
    "inception_messages",
    "inception_sessions",
    "audit_events",
    "projects",
]


async def _wipe_obsolete_agents() -> int:
    """Delete rows for v3 PM-era agents AND every auto-generated agent.

    Per the plan, the 9 auto-generated Unity workers seeded in past Phase
    5 runs all had a stripped-down tool set; rather than enumerate them
    we drop all `is_auto_generated=1` rows. Seeded ones (PM-era +
    Crew pool) stay.
    """
    deleted = 0

    # 1) named obsolete agents
    for role in _OBSOLETE_AGENT_ROLES:
        rows = await crud.get_all("agents", "role = ?", (role,))
        for r in rows:
            await crud.delete_by_id("agents", r["id"])
            deleted += 1
            log.info("wipe_v4.deleted_agent", role=role, id=r["id"])

    # 2) ALL auto-generated agents (Phase 5 of v3 created these on the
    #    fly; tool sets are stale; v4 phase 5 will only pick from seeded
    #    pool so they are useless and confuse the menu).
    autogen = await crud.get_all("agents", "is_auto_generated = 1")
    for r in autogen:
        await crud.delete_by_id("agents", r["id"])
        deleted += 1
        log.info("wipe_v4.deleted_autogen_agent",
                 role=r.get("role"), id=r["id"])

    # 3) standalone VFX Artist row — Crew pool will re-seed a fresh one
    #    with the right tools. (Idempotent — if seed already ran, no-op.)
    vfx = await crud.get_all("agents", "role = ?", ("VFX Artist",))
    for r in vfx:
        await crud.delete_by_id("agents", r["id"])
        deleted += 1
        log.info("wipe_v4.deleted_vfx_artist", id=r["id"])

    return deleted


async def _wipe_projects_and_sessions() -> dict[str, int]:
    """Truncate project-scoped tables. Returns counts deleted per table."""
    counts: dict[str, int] = {}
    for table in _WIPE_TABLES:
        try:
            rows = await crud.get_all(table)
        except Exception as exc:  # noqa: BLE001 — table may not exist on fresh DB
            log.info("wipe_v4.skip_missing_table", table=table, error=str(exc))
            counts[table] = 0
            continue
        n = 0
        for r in rows:
            try:
                await crud.delete_by_id(table, r["id"])
                n += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("wipe_v4.row_delete_failed",
                            table=table, id=r.get("id"), error=str(exc))
        counts[table] = n
        if n:
            log.info("wipe_v4.table_cleared", table=table, rows=n)
    return counts


def _backup_db() -> str | None:
    if not DB_PATH.exists():
        return None
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DB_PATH.with_name(f"mycrew.db.pre-v4.{ts}")
    try:
        shutil.copy2(DB_PATH, backup_path)
        log.info("wipe_v4.db_backup_made", src=str(DB_PATH), dst=str(backup_path))
        return str(backup_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("wipe_v4.backup_failed", error=str(exc))
        return None


async def run_v4_reset_once() -> dict:
    """Run the one-shot reset if not already done. Idempotent + safe to
    call on every boot."""
    if _FLAG.exists():
        return {"skipped": True, "reason": "flag_present", "flag": str(_FLAG)}

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    backup = _backup_db()
    project_counts = await _wipe_projects_and_sessions()
    agents_deleted = await _wipe_obsolete_agents()

    summary = {
        "skipped": False,
        "backup": backup,
        "projects_wiped": project_counts,
        "agents_deleted": agents_deleted,
    }
    _FLAG.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("wipe_v4.complete", **summary)
    return summary
