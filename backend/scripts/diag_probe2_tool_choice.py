"""Layer 0 / Probe 2: tool_choice 强制行为实测 (Qwen)。

回答：Layer 2 的 verify_outputs 用 `tool_choice={"type":"function","function":{"name":"verify_outputs"}}`
强制 Qwen 调用——这条路真的有效吗？还是 LiteLLM 静默降级到 auto？

设计：
  - 直接调 LiteLLM.acompletion（绕开 CrewAI）
  - 3 个 tool 在 tool list 里
  - 测试 3 种 tool_choice，N=5 each：
    A. tool_choice="auto"              — 基线
    B. tool_choice="required"          — 通用强制
    C. tool_choice={type:function,function:{name:"verify_outputs"}}
                                       — 精确强制 verify_outputs
  - 关键指标：返回的 tool_calls[0].function.name 真等于 verify_outputs？

Run:
  backend/.venv/Scripts/python.exe scripts/diag_probe2_tool_choice.py
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
TRIALS = 5

PROVIDER_NAME = "Qwen"
LITELLM_PREFIX = "dashscope"
MODEL = "qwen-plus"

# 3 tools — verify_outputs + 2 distractors
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "verify_outputs",
            "description": "Verify the listed files exist on disk. Call this once you've finished writing files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["file_paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files in a directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
]

# Ambiguous prompt — model could plausibly call any of the 3 tools.
SYSTEM = "You are a build assistant working in a Unity project."
USER = (
    "I want to set up a fruit ninja project. Please decide what to do — "
    "you can look at directories, write files, or verify outputs. Make a single choice."
)


def load_provider() -> tuple[str, str]:
    db = sqlite3.connect(str(ROOT / "data" / "db" / "mycrew.db"))
    db.row_factory = sqlite3.Row
    r = db.execute(
        "SELECT base_url, api_key_ref FROM llm_providers WHERE name=?", (PROVIDER_NAME,),
    ).fetchone()
    db.close()
    return r["base_url"], r["api_key_ref"]


async def call_once(base_url: str, api_key: str, tool_choice) -> dict:
    import litellm
    out = {"error": None, "finish_reason": None, "tool_name": None,
           "args": None, "content_len": 0}
    try:
        resp = await litellm.acompletion(
            model=f"{LITELLM_PREFIX}/{MODEL}",
            api_key=api_key,
            base_url=base_url,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": USER},
            ],
            tools=TOOLS,
            tool_choice=tool_choice,
            temperature=0.5,  # higher temp to surface any randomness
            max_tokens=256,
        )
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        return out
    choice0 = resp.choices[0]
    out["finish_reason"] = choice0.finish_reason
    msg = choice0.message
    tcs = getattr(msg, "tool_calls", None) or []
    if tcs:
        fn = tcs[0].function
        out["tool_name"] = fn.name
        out["args"] = (fn.arguments or "")[:200]
    out["content_len"] = len(getattr(msg, "content", "") or "")
    return out


async def main():
    base_url, api_key = load_provider()
    print(f"Probe 2: tool_choice enforcement on {LITELLM_PREFIX}/{MODEL}\n")
    print(f"Trials per mode: {TRIALS}\n")

    modes = [
        ("A_auto", "auto"),
        ("B_required", "required"),
        ("C_specific", {
            "type": "function",
            "function": {"name": "verify_outputs"},
        }),
    ]
    all_results = {}
    for label, tc in modes:
        print(f"{'=' * 60}\n  {label}  tool_choice={tc!r}\n{'=' * 60}")
        trials = []
        for i in range(TRIALS):
            r = await call_once(base_url, api_key, tc)
            trials.append(r)
            tag = (
                "ERR " + r["error"][:60] if r["error"]
                else f"{r['finish_reason']} → {r['tool_name'] or '<none>'}"
            )
            print(f"  trial {i+1}: {tag}")
        all_results[label] = trials

    print(f"\n{'#' * 60}\n  TALLY\n{'#' * 60}")
    for label, trials in all_results.items():
        n = len(trials)
        errs = sum(1 for t in trials if t["error"])
        any_tool = sum(1 for t in trials if t["tool_name"])
        verify_specific = sum(1 for t in trials if t["tool_name"] == "verify_outputs")
        print(f"\n  {label}:")
        print(f"    errors                : {errs}/{n}")
        print(f"    any tool fired        : {any_tool}/{n}")
        print(f"    verify_outputs fired  : {verify_specific}/{n}")
        tool_names = [t["tool_name"] for t in trials if t["tool_name"]]
        if tool_names:
            from collections import Counter
            print(f"    distribution          : {dict(Counter(tool_names))}")

    out = ROOT / "data" / "diag_probe2_results.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n  Full results: {out}")


if __name__ == "__main__":
    asyncio.run(main())
