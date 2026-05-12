"""Remove records that aren't part of the v2 import (likely leftover from earlier dev/testing)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.repo import crud
from infra.repo.sqlite_repo import init_db, close_db


# IDs to keep: matched by name. Anything else gets removed.
EXPECTED = {
    "llm_providers": {"Claude", "GPT", "Qwen", "GLM", "DeepSeek", "MiMo"},
    "mcp_servers": {"comfyui", "unity", "blender", "git", "tavily", "figma", "notion"},
}


async def main() -> None:
    await init_db()
    for table, names in EXPECTED.items():
        rows = await crud.get_all(table)
        for r in rows:
            if r["name"] not in names:
                await crud.delete_by_id(table, r["id"])
                print(f"  - removed {table}/{r['name']} ({r['id']})")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
