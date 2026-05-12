"""Disable auto_start on all MCP servers (one-time fix for startup hangs).

Run once after importing v2 configs if the MCP commands (npx ..., uvx ...)
aren't installed on your machine. Servers stay in DB and remain `enabled`
so you can connect them manually from the Settings page when ready.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.repo import crud
from infra.repo.sqlite_repo import init_db, close_db


async def main() -> None:
    await init_db()
    rows = await crud.get_all("mcp_servers")
    changed = 0
    for r in rows:
        if r.get("auto_start"):
            await crud.update_by_id("mcp_servers", r["id"], {"auto_start": 0})
            changed += 1
            print(f"  - {r['name']} auto_start → 0")
    print(f"\nDone. {changed} servers updated.")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
