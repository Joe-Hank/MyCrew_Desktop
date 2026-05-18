"""Capacity test: how many code-contract signatures can an LLM reliably
implement in a single .cs file?

For each N in --grid (default 5/10/20/30/50/80), runs --trials trials.
Each trial:
  1. Generate a fake code_contract with 1 class + (N-1) mixed members
     (~40% properties, 40% methods, 20% events). All names are distinct.
  2. Build a prompt mimicking the contract-injected Executor description
     from crewai_runner (post-2026-05-18 commit ab4efbb).
  3. Single-shot LLM completion via the existing llm_gateway (no Crew,
     no tools, no MCP — pure code generation).
  4. Extract C# code from the response (```csharp fence or first
     plausible block).
  5. Regex-check coverage: how many of the N signatures appear literally
     in the generated code. ok = missing == 0.

Outputs:
  - Console: per-trial line + final per-N table (success rate, avg
    missing, avg tokens, avg seconds).
  - JSON: scripts/stress_test_contract_capacity_report.json

Bypasses CrewAI completely to isolate the LLM's raw generative capacity.
The Crew-runtime loop (max_iter, find_in_file self-audit) would only
*increase* the success rate, so this gives a lower bound.

Usage (from backend/ with venv active):

    python -m scripts.stress_test_contract_capacity \\
        --llm-id prov_ee599ffe39ac:deepseek-v4-pro \\
        --grid 5,10,20,30,50,80 --trials 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.WARNING)


# ── Fake-contract generator ─────────────────────────────────────────

_NOUNS = [
    "Score", "Lives", "Health", "Mana", "Energy", "Speed", "Power",
    "Damage", "Armor", "Range", "Cooldown", "Charge", "Ammo", "Stamina",
    "Position", "Velocity", "Rotation", "Direction", "Target", "Origin",
    "Spawn", "Respawn", "Death", "Pickup", "Reward", "Combo", "Streak",
    "Level", "Stage", "Wave", "Boss", "Mob", "Enemy", "Ally", "Player",
    "Camera", "Light", "Shadow", "Audio", "Sfx", "Bgm", "Music",
    "Inventory", "Slot", "Item", "Weapon", "Skill", "Buff", "Debuff",
    "Quest", "Goal", "Objective", "Mission", "Achievement", "Save",
    "Load", "Config", "Setting", "Preference", "Profile", "Stats",
    "Trigger", "Collider", "Sensor", "Detector", "Spawner", "Pool",
    "Frame", "Tick", "Time", "Delta", "Phase", "State", "Mode",
    "Region", "Zone", "Tile", "Block", "Cell", "Path", "Route", "Map",
    "Inventory2", "Treasure", "Trap", "Door", "Key", "Lock", "Switch",
    "Lever", "Button", "Crystal", "Shard", "Orb", "Rune", "Gem",
    "Aura", "Field", "Beam", "Ray", "Pulse", "Wave2", "Explosion",
]

_TYPES = ["int", "float", "bool", "Vector2", "Vector3", "string", "Color"]
_EVENT_PAYLOADS = ["", "int", "float", "Vector2", "string"]


def _gen_signatures(class_name: str, n_members: int, seed: int) -> list[dict]:
    """Generate (n_members) distinct member signatures for a fake class."""
    import random
    rng = random.Random(seed)
    nouns = rng.sample(_NOUNS, k=min(n_members + 5, len(_NOUNS)))
    members: list[dict] = []
    for i in range(n_members):
        roll = rng.random()
        n = nouns[i]
        if roll < 0.40:  # property
            t = rng.choice(_TYPES)
            sig = f"public {t} {n} {{ get; private set; }}"
            members.append({"kind": "property", "signature": sig, "name": n})
        elif roll < 0.80:  # method
            verbs = ["Set", "Reset", "Add", "Remove", "Apply", "Compute",
                    "Refresh", "Sync", "Notify", "Handle", "Trigger"]
            verb = rng.choice(verbs)
            arg_t = rng.choice(_TYPES)
            # Param name MUST NOT be a C# keyword. arg_t.lower() makes
            # int/bool/float/string into keywords → LLM correctly escapes
            # to @bool / @int and misses the literal-match contract.
            # Use `argN` which is always valid + unique per method.
            arg_name = f"arg{i}"
            mname = f"{verb}{n}"
            sig = f"public void {mname}({arg_t} {arg_name})"
            members.append({"kind": "method", "signature": sig, "name": mname})
        else:  # event
            payload = rng.choice(_EVENT_PAYLOADS)
            ename = f"On{n}Changed"
            if payload:
                sig = f"public event Action<{payload}> {ename}"
            else:
                sig = f"public event Action {ename}"
            members.append({"kind": "event", "signature": sig, "name": ename})
    return members


def _gen_contract(n_total: int, seed: int) -> dict:
    """Build a fake single-class code_contract with n_total exports
    (1 class signature + n_total-1 members)."""
    class_name = f"Test{seed:04d}Manager"
    path = f"Assets/Scripts/Test/{class_name}.cs"
    n_members = max(0, n_total - 1)
    members = _gen_signatures(class_name, n_members, seed)
    class_export = {
        "kind": "class",
        "signature": f"public class {class_name} : MonoBehaviour",
        "name": class_name,
    }
    return {
        "namespace": "MyGame.Test",
        "files": [{
            "path": path,
            "exports": [class_export] + members,
        }],
        "imports": [],
    }


# ── Prompt construction (mirrors crewai_runner.run_crew_step_with_crewai) ─


def _build_prompt(contract: dict) -> str:
    f = contract["files"][0]
    path = f["path"]
    exports = f["exports"]
    n_total = len(exports)
    ns = contract.get("namespace") or ""

    lines = [
        "# 角色",
        "你是 Unity Developer，负责按 PM code_contract 实现 C# 脚本。",
        "",
        "# 任务",
        f"实现 `{path}` 单文件。",
        f"namespace: `{ns}`",
        "",
        f"## 🔴 代码契约（PM 已钉死，逐条实现 + 自审）",
        f"本 task 共有 **{n_total} 个 public 符号必须出现在产出的 .cs 文件中**，"
        "缺一个 → task 整体 validation_failed。逐条核对，不要 // TODO 占位，"
        "不要漏写 event/property/method 任一种。",
        "",
        f"### `{path}` — {n_total} 个符号",
    ]
    for e in exports:
        lines.append(f"  - `[{e['kind']}]` {e['signature']}")
    lines += [
        "",
        "# 输出格式",
        "**只输出完整的 .cs 文件内容**，包在 ```csharp ... ``` 代码块里。",
        "不要解释、不要列待办、不要寒暄。",
        "方法体可以简单（如返回默认值、留 `// stub` 一行注释），"
        "**但每个 signature 必须字面完整出现**——包括 modifier、类型、名字、参数列表。",
    ]
    return "\n".join(lines)


# ── Coverage check ──────────────────────────────────────────────────


_FENCE_RE = re.compile(r"```(?:csharp|c#|cs)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_cs(response_text: str) -> str:
    """Extract C# code from fenced block; fall back to raw text."""
    m = _FENCE_RE.search(response_text or "")
    if m:
        return m.group(1)
    return response_text or ""


def _check_coverage(cs: str, contract: dict) -> dict:
    """Regex-check that each signature literally appears in the code.

    **Uses the production `normalize_csharp` from
    domain.qa.contract_validator** so this test measures THE SAME thing
    workflow_svc._verify_code_contract checks at runtime. Without this
    same normalization, the test would report missing signatures that
    production would accept (false positives) — discrediting the curve."""
    from domain.qa.contract_validator import normalize_csharp
    norm = normalize_csharp(cs)
    exports = contract["files"][0]["exports"]
    missing: list[dict] = []
    for e in exports:
        sig_norm = normalize_csharp(e["signature"])
        if not sig_norm:
            continue
        if sig_norm not in norm:
            missing.append({"kind": e["kind"], "signature": e["signature"]})
    return {
        "n_total": len(exports),
        "n_present": len(exports) - len(missing),
        "missing": missing,
        "ok": len(missing) == 0,
    }


# ── LLM driver ──────────────────────────────────────────────────────


async def _call_llm(llm_id: str, prompt: str, max_tokens: int = 8000) -> tuple[str, dict]:
    """Single LLM completion via the existing gateway. Returns (text, usage)."""
    from infra.llm.gateway import llm_gateway
    from infra.llm.base import LlmMessage

    provider_id, model_name = llm_id.split(":", 1)
    msgs = [LlmMessage(role="user", content=prompt)]
    resp = await llm_gateway.chat(
        provider_id, model_name, msgs,
        max_tokens=max_tokens, temperature=0.2,
    )
    usage = {
        "in": resp.usage.prompt_tokens if resp.usage else 0,
        "out": resp.usage.completion_tokens if resp.usage else 0,
    }
    return resp.text or "", usage


# ── Trial driver ────────────────────────────────────────────────────


async def _run_trial(n: int, trial_idx: int, llm_id: str, seed: int) -> dict:
    contract = _gen_contract(n, seed)
    prompt = _build_prompt(contract)
    started = time.monotonic()
    try:
        resp_text, usage = await _call_llm(llm_id, prompt)
    except Exception as exc:
        return {
            "n": n, "trial": trial_idx, "seed": seed,
            "status": "exception", "error": f"{type(exc).__name__}: {exc}",
            "elapsed_s": round(time.monotonic() - started, 2),
            "ok": False,
        }
    elapsed = round(time.monotonic() - started, 2)
    cs = _extract_cs(resp_text)
    cov = _check_coverage(cs, contract)
    return {
        "n": n, "trial": trial_idx, "seed": seed,
        "status": "done",
        "elapsed_s": elapsed,
        "input_tokens": usage["in"],
        "output_tokens": usage["out"],
        "n_total": cov["n_total"],
        "n_present": cov["n_present"],
        "n_missing": len(cov["missing"]),
        "ok": cov["ok"],
        "missing_sample": [m["signature"] for m in cov["missing"][:5]],
        "cs_len_chars": len(cs),
        # Keep raw output for forensics — capacity tests routinely need
        # to inspect "why did this signature get rejected" after the fact.
        "cs_raw": cs,
    }


# ── Aggregation / report ────────────────────────────────────────────


def _format_table(by_n: dict[int, list[dict]]) -> None:
    print()
    print("=" * 76)
    print(f"  {'N':>4} | {'success/trials':>14} | {'success%':>9} | {'avg miss':>9} | "
          f"{'avg out':>8} | {'avg sec':>8}")
    print("-" * 76)
    for n in sorted(by_n.keys()):
        runs = by_n[n]
        succ = sum(1 for r in runs if r["ok"])
        total = len(runs)
        rate = succ * 100 // total if total else 0
        avg_miss = sum(r.get("n_missing", 0) for r in runs) / total if total else 0
        avg_out = sum(r.get("output_tokens", 0) for r in runs) / total if total else 0
        avg_t = sum(r["elapsed_s"] for r in runs) / total if total else 0
        print(f"  {n:>4} | {succ:>2}/{total:<11} | {rate:>7}% | {avg_miss:>9.1f} | "
              f"{avg_out:>8.0f} | {avg_t:>7.1f}s")
    print("=" * 76)


async def amain(args: argparse.Namespace) -> None:
    grid = [int(x) for x in args.grid.split(",") if x.strip()]
    print(f"Using LLM: {args.llm_id}")
    print(f"Grid: N ∈ {grid}, trials/N = {args.trials}, concurrency = {args.concurrency}")
    print()

    sem = asyncio.Semaphore(args.concurrency)
    seed_counter = args.seed

    async def bounded(n: int, ti: int, seed: int) -> dict:
        nonlocal seed_counter
        async with sem:
            r = await _run_trial(n, ti, args.llm_id, seed)
        glyph = "✓" if r["ok"] else ("💥" if r["status"] == "exception" else "✗")
        miss = r.get("n_missing", "?")
        print(f"  N={n:>3} t={ti:>2} {glyph}  miss={miss}/{n}  "
              f"out={r.get('output_tokens',0):>5}  {r['elapsed_s']:>5.1f}s")
        return r

    tasks = []
    for n in grid:
        for ti in range(args.trials):
            tasks.append(bounded(n, ti, seed_counter))
            seed_counter += 1
    results = await asyncio.gather(*tasks)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\n  Full report → {out_path}")

    by_n: dict[int, list[dict]] = {}
    for r in results:
        by_n.setdefault(r["n"], []).append(r)
    _format_table(by_n)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--llm-id", required=True,
                   help="format 'provider_id:model_name'")
    p.add_argument("--grid", default="5,10,20,30,50,80",
                   help="comma-separated N values to test")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--seed", type=int, default=10000,
                   help="starting seed (each trial uses seed+1)")
    p.add_argument("--output", type=str,
                   default="scripts/stress_test_contract_capacity_report.json")
    args = p.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
