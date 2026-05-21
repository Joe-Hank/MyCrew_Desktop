"""Reset stale-done tasks in proj_9280b9f71422 (水果忍者).

Why: 2026-05-21 Phase 4 finding — before the Layer 2 server-side disk
truth check was deployed, Crew runs marked tasks as `status=done`
based purely on captured payload schema validity. With Qwen +
Task(output_pydantic=Spec), the agent skipped tool calls 5/5 trials,
so the captured payload had `file_paths=[...]` but no files existed on
disk. Those tasks now sit in DB as done while their declared files
are absent — downstream code Crews see "✓ done, files ready" but a
ls of project_root shows them missing.

This script finds every task where:
  - project_id = proj_9280b9f71422
  - kind = regular (not crew / setup / final_qa)
  - status = done
  - output_paths is non-empty
  - at least one file in output_paths does NOT exist (or is 0 bytes)

and resets it to pending + clears stale captured payload references so
the new architecture (no output_pydantic + verify_outputs tool +
server-side disk check) gets a fresh shot.

Run from backend/ with venv:
    backend/.venv/Scripts/python.exe scripts/reset_fruit_ninja_stale_done.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "db" / "mycrew.db"
PID = "proj_9280b9f71422"


def _files_ok(rel_paths: list[str], project_root: Path) -> tuple[bool, list[str]]:
    """Return (all_present, missing_or_empty_list)."""
    missing: list[str] = []
    for rel in rel_paths:
        if not isinstance(rel, str) or not rel.strip():
            continue
        abs_path = (
            Path(rel) if Path(rel).is_absolute()
            else (project_root / rel)
        )
        try:
            if not abs_path.exists():
                missing.append(rel)
                continue
            if abs_path.is_file() and abs_path.stat().st_size == 0:
                missing.append(rel + " (0 bytes)")
        except (OSError, PermissionError):
            missing.append(rel + " (perm error)")
    return (not missing), missing


def main():
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    proj = cur.execute(
        "SELECT root_path FROM projects WHERE id=?", (PID,),
    ).fetchone()
    if not proj or not proj["root_path"]:
        print(f"Project {PID} has no root_path; aborting.")
        return
    project_root = Path(proj["root_path"])
    print(f"Project root: {project_root}")

    cur.execute(
        "SELECT id, title, kind, status, output_paths "
        "FROM tasks WHERE project_id=? AND status='done' AND kind='regular'",
        (PID,),
    )
    done_regulars = [dict(r) for r in cur.fetchall()]
    print(f"\nTasks status=done kind=regular: {len(done_regulars)}")

    stale: list[dict] = []
    for r in done_regulars:
        paths_raw = r.get("output_paths") or "[]"
        try:
            paths = json.loads(paths_raw)
        except (json.JSONDecodeError, TypeError):
            paths = []
        if not paths:
            continue
        ok, missing = _files_ok(paths, project_root)
        if not ok:
            stale.append({**r, "_missing": missing})

    print(f"\nStale-done tasks (status=done but files missing): {len(stale)}")
    for r in stale:
        title = r["title"]
        print(f"  - {r['id'][:14]} | {title}")
        for m in r["_missing"][:4]:
            print(f"      missing: {m}")

    if not stale:
        print("\nNo stale-done tasks to reset.")
        con.close()
        return

    # Reset each stale task back to pending. Clear captured-payload
    # references the runner left behind so the rerun starts fresh.
    for r in stale:
        cur.execute(
            "UPDATE tasks SET status='pending', last_error=NULL, "
            "last_error_kind=NULL, finished_at=NULL, io_out_ref=NULL "
            "WHERE id=?",
            (r["id"],),
        )
    print(f"\nReset {len(stale)} stale-done task(s) → pending.")

    # If any of these stale tasks have a parent crew that's also done,
    # the parent crew won't re-dispatch them. Cascade parent status back
    # to pending so workflow_svc re-walks the sequence. Same logic as
    # reset_fruit_ninja_failed.py.
    parent_ids: set[str] = {
        r.get("parent_task_id")
        for r in stale
        if r.get("parent_task_id")
    }
    if parent_ids:
        marks = ",".join("?" * len(parent_ids))
        cur.execute(
            f"UPDATE tasks SET status='pending', last_error=NULL, "
            f"last_error_kind=NULL WHERE id IN ({marks}) AND status='done'",
            tuple(parent_ids),
        )
        print(f"Reset {cur.rowcount} parent crew row(s) cascading the stale reset.")

    # Walk up: parent crews that hold these children — those that are
    # status=done but now have pending children — also need reset. The
    # original reset_fruit_ninja_failed.py has the same logic; replicate
    # here so this script can run standalone.
    cur.execute(
        "SELECT id, title FROM tasks "
        "WHERE project_id=? AND kind='crew' AND status='done'",
        (PID,),
    )
    crew_parents = [dict(r) for r in cur.fetchall()]
    for cp in crew_parents:
        c = cur.execute(
            "SELECT COUNT(*) AS c FROM tasks "
            "WHERE parent_task_id=? AND status='pending'",
            (cp["id"],),
        ).fetchone()
        if (c["c"] or 0) > 0:
            cur.execute(
                "UPDATE tasks SET status='pending', last_error=NULL, "
                "last_error_kind=NULL WHERE id=?",
                (cp["id"],),
            )
            print(f"Reset crew parent {cp['id'][:14]} ({cp['title']}) → pending "
                  f"(had {c['c']} pending children)")

    # Project back to running so workflow_svc picks it up next loop.
    cur.execute("UPDATE projects SET state='running' WHERE id=?", (PID,))
    print(f"\nProject {PID} state → running.")

    con.commit()
    con.close()
    print("\nDone. Restart backend (or wait for next workflow tick) — the project "
          "will retry these tasks with the new architecture (no output_pydantic + "
          "verify_outputs + server-side disk truth check).")


if __name__ == "__main__":
    main()
