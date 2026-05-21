"""Standalone diagnosis for the PM v6 "forced tool_choice returns no
tool_call" failure.

What it does:
  1. Pulls the DeepSeek provider + api_key from the same DB the backend
     reads.
  2. Builds a TINY tool spec (1 string arg, no nesting) — eliminates
     schema complexity as a variable.
  3. Calls `litellm.acompletion` three ways:
       A. tool_choice="auto"            — does flash even know to call?
       B. tool_choice="required"        — does generic-required work?
       C. tool_choice={function: name}  — the strict mode PM v6 uses
  4. For each: prints whether tool_calls came back, dumps args + finish
     reason + the raw HTTP response shape.

Run from backend/ with venv: `python scripts/diag_forced_tool_choice.py`
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path


sys.stdout.reconfigure(encoding="utf-8")


def load_provider() -> tuple[str, str, str]:
    db = sqlite3.connect(
        str(Path(__file__).parent.parent.parent / "data" / "db" / "mycrew.db")
    )
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute(
        "SELECT base_url, api_key_ref FROM llm_providers WHERE type='deepseek'"
    )
    r = cur.fetchone()
    if not r:
        raise SystemExit("No deepseek provider in DB.")
    return r["base_url"], r["api_key_ref"], "deepseek/deepseek-v4-flash"


TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "echo_message",
        "description": "Echo the given message back. ALWAYS call this tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Any short string to echo.",
                },
            },
            "required": ["message"],
        },
    },
}


async def call(*, label: str, tool_choice, model: str, base_url: str, api_key: str):
    import litellm

    print(f"\n{'=' * 60}")
    print(f"[{label}]  tool_choice={tool_choice!r}")
    print("=" * 60)
    try:
        resp = await litellm.acompletion(
            model=model,
            api_key=api_key,
            base_url=base_url,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a tool-calling assistant. You MUST call the "
                        "echo_message tool exactly once with a short string."
                    ),
                },
                {"role": "user", "content": "Hello world"},
            ],
            tools=[TOOL_SPEC],
            tool_choice=tool_choice,
            temperature=0.2,
            max_tokens=256,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
        return

    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None) or []
    content = getattr(msg, "content", "") or ""
    finish = resp.choices[0].finish_reason

    print(f"  finish_reason: {finish}")
    print(f"  content (len={len(content)}): {content[:200]!r}")
    print(f"  tool_calls count: {len(tool_calls)}")
    for i, tc in enumerate(tool_calls):
        fn = tc.function
        print(f"  tool_call[{i}]: name={fn.name}  args={fn.arguments[:200]!r}")

    # Also dump the raw response dict for the curious
    try:
        if hasattr(resp, "model_dump"):
            raw = resp.model_dump()
        else:
            raw = resp.__dict__
        # First 1500 chars only
        print(f"\n  raw shape (1500c): {json.dumps(raw, default=str, ensure_ascii=False)[:1500]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  (raw dump failed: {exc})")


async def main():
    base_url, api_key, model = load_provider()
    print(f"Provider: base_url={base_url}  model={model}  api_key={api_key[:10]}...")

    for label, tc in [
        ("A. tool_choice='auto'", "auto"),
        ("B. tool_choice='required'", "required"),
        (
            "C. tool_choice={function: echo_message}",
            {"type": "function", "function": {"name": "echo_message"}},
        ),
    ]:
        await call(
            label=label, tool_choice=tc, model=model,
            base_url=base_url, api_key=api_key,
        )


if __name__ == "__main__":
    asyncio.run(main())
