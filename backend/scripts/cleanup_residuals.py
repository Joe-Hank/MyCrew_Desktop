"""Delete all project residuals (DB rows + output/ directories + orphan
inception sessions). Safe to re-run.

Run from `backend/` dir:
    python scripts/cleanup_residuals.py

The user-level entities below are KEPT:
  - llm_providers + llm_models           (user's LLM keys)
  - mcp_servers                          (user's MCP config)
  - tools                                (seeded + custom tools)
  - agents where is_auto_generated=0     (team page entries)
  - permissions, app_settings            (user prefs)
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

# Make sibling imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.repo import crud  # noqa: E402
from bootstrap.paths import OUTPUT_DIR  # noqa: E402


async def main() -> None:
    # 1. Delete all projects + cascading tasks / sessions / messages
    projects = await crud.get_all("projects")
    print(f"Found {len(projects)} project rows")
    for p in projects:
        pid = p["id"]
        # tasks
        tasks = await crud.get_all("tasks", "project_id = ?", (pid,))
        for t in tasks:
            await crud.delete_by_id("tasks", t["id"])
        # inception sessions + messages
        sessions = await crud.get_all("inception_sessions",
                                        "project_id = ?", (pid,))
        for s in sessions:
            msgs = await crud.get_all("inception_messages",
                                        "session_id = ?", (s["id"],))
            for m in msgs:
                await crud.delete_by_id("inception_messages", m["id"])
            await crud.delete_by_id("inception_sessions", s["id"])
        await crud.delete_by_id("projects", pid)
        name_ascii = (p.get('name', '?')[:30]
                       .encode('ascii', 'replace').decode('ascii'))
        print(f"  -project {pid} ({name_ascii}): "
              f"{len(tasks)} tasks, {len(sessions)} sessions purged")

    # 2. Delete orphan inception sessions (project_id is NULL — drafts the
    # user opened but never finished)
    orphans = await crud.get_all("inception_sessions",
                                   "project_id IS NULL")
    print(f"Found {len(orphans)} orphan sessions (no project bound)")
    for s in orphans:
        msgs = await crud.get_all("inception_messages",
                                    "session_id = ?", (s["id"],))
        for m in msgs:
            await crud.delete_by_id("inception_messages", m["id"])
        await crud.delete_by_id("inception_sessions", s["id"])
        print(f"  -orphan session {s['id']} ({len(msgs)} msgs)")

    # 3. Delete auto-generated crews (these are scaffolded by Plan Maker
    # per-project; user-created crews keep)
    crews = await crud.get_all("crews", "is_auto_generated = ?", (1,))
    print(f"Found {len(crews)} auto-generated crews")
    for c in crews:
        await crud.delete_by_id("crews", c["id"])
        print(f"  -crew {c['id']} ({c.get('name','?')})")

    # 4. Delete output/ subdirectories
    out_root = Path(OUTPUT_DIR)
    if out_root.exists():
        subdirs = [p for p in out_root.iterdir() if p.is_dir()]
        print(f"Found {len(subdirs)} output/ subdirectories")
        for sd in subdirs:
            try:
                shutil.rmtree(sd)
                print(f"  -removed {sd}")
            except Exception as exc:
                print(f"  X failed {sd}: {exc}")

    print("\nDone. Configuration / agents / providers / tools all preserved.")


if __name__ == "__main__":
    asyncio.run(main())
