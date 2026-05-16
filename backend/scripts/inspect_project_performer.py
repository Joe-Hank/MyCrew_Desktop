"""One-off: dump the newest project matching a substring to inspect
performer_kind / performer_id propagation from Plan Maker → DB.

Usage:
    python scripts/inspect_project_performer.py 祖玛

Prints the project row + every task's (title, agent_id, performer_kind,
performer_id) so you can tell at a glance whether Phase 5's PM v4
assignments survived the save.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main(needle: str) -> int:
    db = Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db"
    if not db.exists():
        print(f"DB not found: {db}")
        return 1

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    proj = con.execute(
        "SELECT id, name FROM projects WHERE name LIKE ? "
        "ORDER BY created_at DESC LIMIT 1",
        (f"%{needle}%",),
    ).fetchone()
    if not proj:
        print(f"no project matching {needle!r}")
        return 1

    print(f"project: {proj['name']}  id={proj['id']}")
    rows = con.execute(
        "SELECT title, agent_id, performer_kind, performer_id "
        "FROM tasks WHERE project_id = ? ORDER BY title",
        (proj["id"],),
    ).fetchall()

    for r in rows:
        title = (r["title"] or "")[:32]
        agent = r["agent_id"] or "NULL"
        kind = r["performer_kind"] or "NULL"
        pid = r["performer_id"] or "NULL"
        print(f"  - {title:<34} agent_id={agent:<24} kind={kind:<6} pid={pid}")

    return 0


if __name__ == "__main__":
    needle = sys.argv[1] if len(sys.argv) > 1 else "祖玛"
    sys.exit(main(needle))
