"""Probe the actual DeepSeek endpoint with the imported key to find the
real failure reason (model_not_found / invalid_api_key / wrong base_url / etc.)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from infra.repo import crud
from infra.repo.sqlite_repo import init_db, close_db


async def main() -> None:
    await init_db()
    providers = await crud.get_all("llm_providers", "name = ?", ("DeepSeek",))
    p = providers[0]
    base_url = p["base_url"]
    api_key = p["api_key_ref"]
    models = await crud.get_all("llm_models", "provider_id = ?", (p["id"],))

    print(f"Base URL : {base_url}")
    print(f"API Key  : {api_key[:6]}...{api_key[-4:]}")
    print()

    async with httpx.AsyncClient(timeout=15) as client:
        # Probe 1: list models
        url_models = base_url.rstrip("/") + "/models"
        print(f"[1] GET {url_models}")
        try:
            r = await client.get(url_models, headers={"Authorization": f"Bearer {api_key}"})
            print(f"    status: {r.status_code}")
            print(f"    body  : {r.text[:500]}")
        except Exception as exc:
            print(f"    error : {exc}")
        print()

        # Probe 2: chat completion with each imported model
        url_chat = base_url.rstrip("/") + "/chat/completions"
        for m in models:
            model_name = m["model_name"]
            print(f"[2] POST {url_chat}  model={model_name}")
            try:
                r = await client.post(
                    url_chat,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 5,
                    },
                )
                print(f"    status: {r.status_code}")
                print(f"    body  : {r.text[:400]}")
            except Exception as exc:
                print(f"    error : {exc}")
            print()

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
