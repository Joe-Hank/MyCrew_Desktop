"""Merge English-named legacy Crews into their Chinese seed equivalents
and drop historical orphan Crews.

Two modes:
  python scripts/cleanup_legacy_crews.py            # dry run (default)
  python scripts/cleanup_legacy_crews.py --apply    # actually mutate DB

Strategy:
  1. For each (english_name, chinese_name) pair in _LEGACY_NAME_MAP:
     - If both rows exist: UPDATE every tasks.performer_id row that
       points at the english id to point at the chinese id, then DELETE
       the english row.
     - If only english exists: rename in place.
     - If only chinese exists: nothing to do.
  2. Drop crew rows that are (a) NOT in SEED_CREWS, (b) NOT named
     `qa_functional` (which is still in active use), and (c) have no
     incoming task references. Keeps anything that's actually live.

Reports every action before/after the --apply.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Orphan Crews from earlier iterations that we explicitly migrate before
# the orphan-drop pass. Each maps to a fallback single-Agent that picks
# up whatever tasks were still bound to the old Crew. After migration
# the Crew has 0 refs and the orphan pass drops it.
ORPHAN_TO_AGENT_ROLE: dict[str, str] = {
    "qa_functional": "QA Engineer",  # PM v4 final_qa is single-agent, not Crew
}

KEEP_ORPHANS: set[str] = set()  # everything else without refs gets dropped


def main(apply: bool) -> int:
    from bootstrap.seed_crews import SEED_CREWS, _LEGACY_NAME_MAP

    db = Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    seed_names = {c["name"] for c in SEED_CREWS}
    actions: list[tuple[str, str]] = []  # (verb, description)

    # Pass 0: migrate orphan-Crew refs to a fallback single-Agent so
    # the orphan Crew can be dropped in pass 2 without leaving tasks
    # stuck on a non-existent performer.
    for orphan_name, fallback_role in ORPHAN_TO_AGENT_ROLE.items():
        orphan_rows = con.execute(
            "SELECT id FROM crews WHERE name = ?", (orphan_name,)
        ).fetchall()
        if not orphan_rows:
            continue
        orphan_id = orphan_rows[0]["id"]
        agent_rows = con.execute(
            "SELECT id FROM agents WHERE role = ?", (fallback_role,)
        ).fetchall()
        if not agent_rows:
            actions.append((
                "skip",
                f"orphan crew {orphan_name!r} → cannot migrate, "
                f"fallback agent role {fallback_role!r} not found",
            ))
            continue
        fallback_id = agent_rows[0]["id"]
        ref_count = con.execute(
            "SELECT COUNT(*) FROM tasks WHERE performer_id = ?", (orphan_id,)
        ).fetchone()[0]
        if ref_count == 0:
            continue  # let pass 2 drop it
        actions.append((
            "migrate",
            f"redirect {ref_count} task(s) from orphan crew "
            f"{orphan_name!r}({orphan_id}) → single agent "
            f"{fallback_role!r}({fallback_id})",
        ))
        if apply:
            con.execute(
                "UPDATE tasks SET performer_kind = 'agent', "
                "performer_id = ?, agent_id = ? "
                "WHERE performer_id = ?",
                (fallback_id, fallback_id, orphan_id),
            )

    # Pass 1: merge English → Chinese.
    for english, chinese in _LEGACY_NAME_MAP.items():
        if english == chinese:
            continue
        en_rows = con.execute(
            "SELECT id FROM crews WHERE name = ?", (english,)
        ).fetchall()
        zh_rows = con.execute(
            "SELECT id FROM crews WHERE name = ?", (chinese,)
        ).fetchall()
        if not en_rows:
            continue
        en_id = en_rows[0]["id"]
        ref_count = con.execute(
            "SELECT COUNT(*) FROM tasks WHERE performer_id = ?", (en_id,)
        ).fetchone()[0]
        if zh_rows:
            zh_id = zh_rows[0]["id"]
            actions.append((
                "merge",
                f"redirect {ref_count} task(s) "
                f"from {english!r}({en_id}) → {chinese!r}({zh_id}), "
                f"then delete {english!r}",
            ))
            if apply:
                con.execute(
                    "UPDATE tasks SET performer_id = ? WHERE performer_id = ?",
                    (zh_id, en_id),
                )
                con.execute("DELETE FROM crews WHERE id = ?", (en_id,))
        else:
            actions.append((
                "rename",
                f"rename {english!r}({en_id}) → {chinese!r} in place "
                f"(no Chinese row exists yet, {ref_count} task refs preserved)",
            ))
            if apply:
                con.execute(
                    "UPDATE crews SET name = ? WHERE id = ?", (chinese, en_id),
                )

    # Pass 2: drop unreferenced orphans (not in SEED_CREWS, not keep-listed).
    all_crews = con.execute(
        "SELECT id, name FROM crews ORDER BY name"
    ).fetchall()
    legacy_set = set(_LEGACY_NAME_MAP.keys())
    for c in all_crews:
        n = c["name"]
        if n in seed_names or n in legacy_set or n in KEEP_ORPHANS:
            continue
        refs = con.execute(
            "SELECT COUNT(*) FROM tasks WHERE performer_id = ?", (c["id"],)
        ).fetchone()[0]
        if refs > 0:
            actions.append((
                "keep",
                f"orphan {n!r}({c['id']}) — kept because {refs} task(s) "
                f"still reference it (manual cleanup needed)",
            ))
            continue
        actions.append((
            "drop",
            f"drop unreferenced orphan {n!r}({c['id']})",
        ))
        if apply:
            con.execute("DELETE FROM crews WHERE id = ?", (c["id"],))

    print(f"=== {'APPLY' if apply else 'DRY RUN'} ===\n")
    for verb, desc in actions:
        print(f"  [{verb}] {desc}")

    if apply:
        con.commit()
        final = con.execute("SELECT COUNT(*) FROM crews").fetchone()[0]
        print(f"\ndone — {final} crew row(s) remain")
    else:
        print(f"\n{len(actions)} action(s) staged. Re-run with --apply to commit.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv))
