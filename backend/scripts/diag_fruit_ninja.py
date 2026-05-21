"""Diagnostic dump for proj_9280b9f71422 (水果忍者)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

DB = str(Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db")
PID = "proj_9280b9f71422"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute("SELECT id, name, state, root_path FROM projects WHERE id=?", (PID,))
proj = dict(cur.fetchone() or {})
print(f"Project: {proj.get('name')} | state={proj.get('state')} | root_path={proj.get('root_path')}")
print()

cur.execute(
    "SELECT id, title, status, kind, parent_task_id, parent_step_index, "
    "performer_kind, performer_id, output_paths, last_error_kind, last_error "
    "FROM tasks WHERE project_id=? ORDER BY rowid",
    (PID,),
)
for r in cur.fetchall():
    d = dict(r)
    parent = (d.get("parent_task_id") or "-")[:12]
    print(
        f"#{d['id'][:12]} | {d['kind']:8} | {d['status']:18} "
        f"| parent={parent} step={d['parent_step_index']} | {d['title']}"
    )
    paths = d.get("output_paths") or ""
    if paths:
        print(f"   paths: {paths[:140]}")
    err = d.get("last_error") or ""
    if err:
        print(f"   [{d.get('last_error_kind')}] {err[:400]}")
con.close()
