"""Quick: dump every crews row so we can tell at a glance whether the
i18n rename pass has run yet (English vs Chinese names).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def main() -> int:
    db = Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, name, is_auto_generated FROM crews ORDER BY name"
    ).fetchall()
    if not rows:
        print("(no crews)")
        return 0
    for r in rows:
        tag = "auto" if r["is_auto_generated"] else "seed"
        print(f"  [{tag}] {r['id']}  {r['name']}")
    print(f"\ntotal: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
