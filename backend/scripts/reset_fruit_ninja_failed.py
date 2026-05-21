"""Reset failed system_impl tasks in proj_9280b9f71422 (水果忍者) so the
project can retry with the role-aware emit_output fix.

Why: All failed tasks failed because Head steps had no write_file tool but
emit_output's path-existence check rejected their (correct) spec payloads.
With make_emit_output_tool(step_role="head") now bypassing the on-disk check,
these should run cleanly. Reset failed → pending, clear last_error, and set
the project state back to running so workflow_svc picks it up.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB = str(Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db")
PID = "proj_9280b9f71422"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute(
    "SELECT id, title, status, parent_task_id FROM tasks "
    "WHERE project_id=? AND status='failed'",
    (PID,),
)
failed = [dict(r) for r in cur.fetchall()]
print(f"Failed tasks to reset: {len(failed)}")
for r in failed:
    print(f"  - {r['id'][:12]} | {r['title']}")

if failed:
    cur.execute(
        "UPDATE tasks SET status='pending', last_error=NULL, last_error_kind=NULL "
        "WHERE project_id=? AND status='failed'",
        (PID,),
    )
    print(f"\nReset {cur.rowcount} task rows → pending.")

# Reset parent crew tasks (status=done but children failed) so they re-dispatch.
cur.execute(
    "SELECT id, title, status FROM tasks "
    "WHERE project_id=? AND kind='crew' AND status='done'",
    (PID,),
)
crew_parents = [dict(r) for r in cur.fetchall()]
for cp in crew_parents:
    # Check if any child of this crew is now pending (i.e. we just reset one).
    cur.execute(
        "SELECT COUNT(*) AS c FROM tasks WHERE parent_task_id=? AND status='pending'",
        (cp["id"],),
    )
    pending_kids = cur.fetchone()["c"]
    if pending_kids > 0:
        cur.execute(
            "UPDATE tasks SET status='pending', last_error=NULL, "
            "last_error_kind=NULL WHERE id=?",
            (cp["id"],),
        )
        print(f"Reset crew parent {cp['id'][:12]} ({cp['title']}) → pending "
              f"(had {pending_kids} pending children)")

# Project back to running so workflow_svc picks it up.
cur.execute("UPDATE projects SET state='running' WHERE id=?", (PID,))
print(f"\nProject {PID} state → running.")

con.commit()
con.close()
print("\nDone. Restart backend (or it will auto-pick) and the project should "
      "now resume with the role-aware emit_output fix.")
