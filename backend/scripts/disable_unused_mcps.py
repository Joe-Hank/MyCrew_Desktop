"""Temporarily disable MCP servers that hang at startup because:
  - figma / tavily / notion: env_ref is a literal ${VAR} placeholder
    (no real token wired), so the server starts but auth-hangs.
  - unity (http): needs Unity Editor + Unity MCP Bridge listening on
    port 8090; if the editor isn't open the connect attempt waits
    out the full timeout (and on Windows ProactorEventLoop the
    wait_for cancellation sometimes doesn't actually free the socket).

Run this once if backend startup hangs after comfyui/git/blender
connect — restart afterwards.

Re-enable individually from the team page when you have a real
token / Unity Editor running.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DISABLE = ("figma", "tavily", "notion", "unity")


def main() -> int:
    db = Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db"
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    cur = con.execute(
        "UPDATE mcp_servers SET auto_start = 0, enabled = 0 "
        "WHERE name IN ({})".format(",".join(["?"] * len(DISABLE))),
        DISABLE,
    )
    con.commit()
    print(f"disabled {cur.rowcount} row(s)")

    print()
    print("Current MCP roster:")
    for r in con.execute(
        "SELECT name, enabled, auto_start FROM mcp_servers ORDER BY name"
    ).fetchall():
        flag = "ON " if (r["enabled"] and r["auto_start"]) else "off"
        print(f"  [{flag}] {r['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
