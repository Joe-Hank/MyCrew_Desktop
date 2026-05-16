"""Drop specific tool rows that have been removed from the runner.

Whitelist-only (intentionally) — there are unused-but-installable tools
in the BUILTIN_TOOLS catalogue (figma_*, tavily_*, manage_probuilder, …)
that the user wants to keep available for future agents. Auto-dropping
"every orphan" would nuke those too. So this script only touches the
names explicitly retired from the catalogue.

Add a name to ``RETIRED_TOOL_NAMES`` whenever you drop something from
seed_builtin_tools.BUILTIN_TOOLS.

Dry-run by default; --apply to commit.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Names that have been removed from BUILTIN_TOOLS and whose DB rows
# should be cleaned up. Keep this in sync with the seed list.
RETIRED_TOOL_NAMES: set[str] = {
    # 2026-05-16 audit: mcp_filesystem variants overlapped with
    # the local_* versions everyone actually used.
    "read_file",
    "list_directory",
}


def main(apply: bool) -> int:
    db = Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        "SELECT id, name FROM tools WHERE name IN ({})".format(
            ",".join("?" * len(RETIRED_TOOL_NAMES)),
        ),
        list(RETIRED_TOOL_NAMES),
    ).fetchall()

    print(f"=== {'APPLY' if apply else 'DRY RUN'} — {len(rows)} retired row(s) ===\n")
    for r in rows:
        print(f"  · {r['id']}  {r['name']}")

    if not rows:
        print("(nothing to drop)")
        return 0

    if apply:
        for r in rows:
            con.execute("DELETE FROM tools WHERE id = ?", (r["id"],))
        con.commit()
        remaining = con.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
        print(f"\ndropped {len(rows)}; {remaining} tool row(s) remain")
    else:
        print(f"\n{len(rows)} would be dropped. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(apply="--apply" in sys.argv))
