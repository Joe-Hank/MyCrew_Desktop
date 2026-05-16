"""Diagnose duplicate / orphan Crew rows.

Lists:
  1. Every Crew row (with task reference count)
  2. Crews that share a logical identity (English vs Chinese variants)
  3. Crews not in the current SEED_CREWS list (historical garbage)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Make the seed list importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from bootstrap.seed_crews import SEED_CREWS, _LEGACY_NAME_MAP

    db = Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    seed_names = {c["name"] for c in SEED_CREWS}
    legacy_to_new = dict(_LEGACY_NAME_MAP)

    crews = con.execute(
        "SELECT id, name, is_auto_generated FROM crews ORDER BY name"
    ).fetchall()

    print(f"== {len(crews)} Crew rows ==\n")
    for c in crews:
        refs = con.execute(
            "SELECT COUNT(*) FROM tasks WHERE performer_id = ?", (c["id"],)
        ).fetchone()[0]
        flag = ""
        if c["name"] in legacy_to_new and legacy_to_new[c["name"]] != c["name"]:
            flag = f"  ← legacy (target='{legacy_to_new[c['name']]}')"
        elif c["name"] in seed_names:
            flag = "  ← current seed"
        else:
            flag = "  ← orphan (not in current SEED_CREWS)"
        print(f"  {c['id']}  refs={refs:<3} name={c['name']!r}{flag}")

    print()
    print("== Merge plan ==")
    for legacy, target in legacy_to_new.items():
        if legacy == target:
            continue
        legacy_rows = con.execute(
            "SELECT id FROM crews WHERE name = ?", (legacy,)
        ).fetchall()
        target_rows = con.execute(
            "SELECT id FROM crews WHERE name = ?", (target,)
        ).fetchall()
        if not legacy_rows:
            print(f"  {legacy!r} → {target!r}: no legacy row (clean)")
            continue
        if not target_rows:
            print(f"  {legacy!r} → {target!r}: rename in place")
            continue
        legacy_id = legacy_rows[0]["id"]
        target_id = target_rows[0]["id"]
        refs = con.execute(
            "SELECT COUNT(*) FROM tasks WHERE performer_id = ?", (legacy_id,)
        ).fetchone()[0]
        print(
            f"  {legacy!r} ({legacy_id}, refs={refs}) → "
            f"merge into {target!r} ({target_id}), delete legacy"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
