"""Sequential driver for the contract capacity stress test.

Reuses `_run_trial` / `_format_table` from stress_test_contract_capacity
but drives trials with a plain `for` loop instead of that script's
amain (which uses asyncio.Semaphore + asyncio.gather and was observed
to wedge entirely when a single LLM call hung — e.g. on a reasoning
model that fell into a long chain-of-thought past the gateway's
90s timeout). The plain loop is robust: one stuck trial blocks just
that trial; the script never enters an undebuggable global-deadlock.

Side benefit: partial JSON save after each trial, so a crash mid-run
doesn't lose data.

Use this in preference to running stress_test_contract_capacity directly
when --concurrency would otherwise be 1 anyway.

Usage (from backend/ with venv active):

    python -m scripts.stress_test_contract_capacity_driver \\
        --llm-id prov_ee599ffe39ac:deepseek-v4-flash \\
        --grid 5,10,20,30,50,80 --trials 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path


async def amain(llm_id: str, grid: list[int], trials: int, seed: int,
                out_path: str) -> None:
    from scripts.stress_test_contract_capacity import _run_trial, _format_table

    print(f"Using LLM: {llm_id}")
    print(f"Grid: N ∈ {grid}, trials/N = {trials}, sequential")
    print()

    results: list[dict] = []
    seed_counter = seed
    total = len(grid) * trials
    done = 0
    started_all = time.monotonic()

    for n in grid:
        for ti in range(trials):
            r = await _run_trial(n, ti, llm_id, seed_counter)
            seed_counter += 1
            done += 1
            glyph = "✓" if r["ok"] else ("💥" if r["status"] == "exception" else "✗")
            miss = r.get("n_missing", "?")
            elapsed = r.get("elapsed_s", 0)
            tokens_out = r.get("output_tokens", 0)
            print(f"  [{done:>2}/{total}] N={n:>3} t={ti:>2} {glyph}  "
                  f"miss={miss}/{n}  out={tokens_out:>5}  {elapsed:>5.1f}s",
                  flush=True)
            results.append(r)
            # Best-effort partial-save after each trial so a crash mid-run
            # doesn't lose data.
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(
                json.dumps(results, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    total_elapsed = time.monotonic() - started_all
    print(f"\n  Full report → {out_path}  (total {total_elapsed:.1f}s)")

    by_n: dict[int, list[dict]] = {}
    for r in results:
        by_n.setdefault(r["n"], []).append(r)
    _format_table(by_n)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--llm-id", required=True)
    p.add_argument("--grid", default="5,10,20,30,50,80")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--seed", type=int, default=20000)
    p.add_argument("--output", type=str,
                   default="scripts/stress_test_contract_capacity_report.json")
    args = p.parse_args()
    grid = [int(x) for x in args.grid.split(",") if x.strip()]
    asyncio.run(amain(args.llm_id, grid, args.trials, args.seed, args.output))


if __name__ == "__main__":
    main()
