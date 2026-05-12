"""Diagnose the imported DeepSeek config."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infra.repo import crud
from infra.repo.sqlite_repo import init_db, close_db


async def main() -> None:
    await init_db()
    providers = await crud.get_all("llm_providers", "name = ?", ("DeepSeek",))
    for p in providers:
        print(f"Provider: {p['name']}")
        print(f"  type      : {p['type']}")
        print(f"  base_url  : {p['base_url']}")
        key = p.get("api_key_ref") or ""
        print(f"  api_key   : {key[:6]}...{key[-4:]} (len={len(key)})")
        models = await crud.get_all("llm_models", "provider_id = ?", (p["id"],))
        print(f"  models    :")
        for m in models:
            print(f"    - {m['model_name']}  (supports_thinking={m.get('supports_thinking')})")
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
