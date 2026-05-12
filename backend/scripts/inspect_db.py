"""Quick inspection of imported data."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.repo import crud
from infra.repo.sqlite_repo import init_db, close_db


async def main() -> None:
    await init_db()
    for table in ("llm_providers", "mcp_servers", "tools", "agents", "crews"):
        rows = await crud.get_all(table)
        print(f"\n## {table} ({len(rows)})")
        for r in rows:
            label = r.get("name") or r.get("role") or r.get("id")
            extra = ""
            if table == "llm_providers":
                extra = f" type={r.get('type')}"
            if table == "agents":
                extra = f" llm={r.get('llm_id')}"
            print(f"  {r['id']:<20} {label}{extra}")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
