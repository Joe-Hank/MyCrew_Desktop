"""Dump everything we know about a stuck/failed task: DB row, sub-step
IO, and OUTPUT_DIR layout, so we can tell whether the failure was a
runner crash, an emit_output rejection, or a mid-step exception.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# Force stdout to UTF-8 so Chinese task titles + sub-step file names
# don't blow up the script in a default Windows GBK PowerShell console.
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def main(needle: str) -> int:
    db = Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        "SELECT id, title, status, project_id, performer_kind, "
        "performer_id, agent_id, last_error, last_error_kind, "
        "io_in_ref, io_out_ref FROM tasks WHERE title LIKE ?",
        (f"%{needle}%",),
    ).fetchall()
    if not rows:
        print(f"no task matching {needle!r}")
        return 1

    for t in rows:
        print(f"\n== task {t['id']}  [{t['title']}]  status={t['status']} ==")
        print(f"  project_id     : {t['project_id']}")
        print(f"  performer      : {t['performer_kind']} / {t['performer_id']}")
        print(f"  agent_id       : {t['agent_id']}")
        print(f"  last_error_kind: {t['last_error_kind']}")
        print(f"  last_error     : {(t['last_error'] or '')[:400]}")
        print(f"  io_in_ref      : {t['io_in_ref']}")
        print(f"  io_out_ref     : {t['io_out_ref']}")

        # Sub-step IO on disk
        out_dir = Path(__file__).resolve().parents[2] / "output"
        sub = out_dir / (t["project_id"] or "") / t["id"] / "sub"
        if sub.exists():
            print(f"  sub/ exists at: {sub}")
            files = sorted(sub.iterdir())
            if not files:
                print("    (empty)")
            for f in files:
                size = f.stat().st_size
                print(f"    {f.name:<40} {size} bytes")
        else:
            print(f"  sub/ does NOT exist at: {sub}")

        # The Crew that should have walked this task
        if t["performer_kind"] == "crew" and t["performer_id"]:
            crew = con.execute(
                "SELECT id, name, agent_sequence FROM crews WHERE id = ?",
                (t["performer_id"],),
            ).fetchone()
            if crew:
                print(f"\n  bound Crew: {crew['name']}  ({crew['id']})")
                try:
                    seq = json.loads(crew["agent_sequence"] or "[]")
                except Exception:
                    seq = []
                for i, step in enumerate(seq):
                    agent_id = step.get("agent_id", "?")
                    agent_row = con.execute(
                        "SELECT role FROM agents WHERE id = ?", (agent_id,)
                    ).fetchone()
                    agent_role = agent_row["role"] if agent_row else "(missing)"
                    print(
                        f"    step {i}  role={step.get('role','?'):<8} "
                        f"agent={agent_role}  ({agent_id})"
                    )

        # Recent events for this task (last 20)
        evt = con.execute(
            "SELECT ts, event_type, payload FROM events "
            "WHERE task_id = ? ORDER BY ts DESC LIMIT 20",
            (t["id"],),
        ).fetchall()
        if evt:
            print(f"\n  recent events ({len(evt)}):")
            for e in evt:
                payload = ""
                try:
                    payload_obj = json.loads(e["payload"] or "{}")
                    payload = json.dumps(payload_obj, ensure_ascii=False)[:160]
                except Exception:
                    payload = (e["payload"] or "")[:160]
                print(f"    {e['ts']}  {e['event_type']:<24} {payload}")

    return 0


if __name__ == "__main__":
    needle = sys.argv[1] if len(sys.argv) > 1 else "美术资产"
    sys.exit(main(needle))
