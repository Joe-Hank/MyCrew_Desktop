"""Stress-test the Plan Maker (PM) flow N times with a fixed prompt.

What it measures per run:
  - status (ready / failed / cancelled / timeout / exception) + failed_phase
  - elapsed seconds
  - input/output tokens + 人民币 cost (read from inception_sessions.pending_*)
  - semantic audit of successful runs — catches "passed Pydantic but
    actually broken" patterns we've hit in production:
      * Pure-doc task (Phase 2/3 should filter, but maybe slipped)
      * code_contract class name ≠ .cs filename stem
      * Audio assets without AudioManager wiring
      * 概念含高分/存档/进度 but no PlayerPrefs/SaveSystem task
      * 概念含主菜单/过关/重开 but no SceneLoader/SceneManager task

Usage (from `backend/` directory, with venv active):

    python -m scripts.stress_test_pm --runs 20 --concurrency 4
    python -m scripts.stress_test_pm --runs 3 --concurrency 1   # smoke
    python -m scripts.stress_test_pm --runs 5 --keep-sessions   # don't cleanup

Output:
  - Console: real-time per-run line + final summary table
  - JSON:    scripts/stress_test_pm_report.json (full per-run records)
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

# Quiet structlog's INFO firehose so console stays readable
logging.basicConfig(level=logging.WARNING)


PROMPT = (
    "复刻吃豆人，美术素材用黑袍纠察队的人物头像，地图是沃特公司"
    "（地形设计按原版吃豆人就行），主控是屠夫（Butcher），幽灵是英雄"
    "（爆竹女、火车人、祖国人、玄色），普通豆子就用金色圆点，"
    "超级豆子是V5化合物试管，Butcher吃到超级豆子就变成超人状态，"
    "可以手撕近身的英雄。当然这些都是美术素材上的要求，图像的尺寸、"
    "像素等可视情况规定。玩法上其实和原版游戏是一致的，没有变化。"
    "游戏做成竖屏，最后要导出为安卓手机游戏"
)


# ── DB helpers ──────────────────────────────────────────────────────


async def _resolve_llm_id() -> str:
    """Pick a usable llm_id from existing config — prefer one whose
    model has a price seeded (so cost tracking shows numbers)."""
    from infra.repo import crud
    providers = await crud.get_all("llm_providers")
    if not providers:
        raise RuntimeError("no llm_providers in DB; configure at least one first")
    for p in providers:
        models = await crud.get_all(
            "llm_models", "provider_id = ?", (p["id"],),
        )
        priced = [m for m in models if (m.get("input_price_cny_per_1m") or 0) > 0]
        pool = priced or models
        if pool:
            return f"{p['id']}:{pool[0]['model_name']}"
    raise RuntimeError("no llm_models in DB; configure at least one provider+model")


async def _create_session(llm_id: str) -> dict:
    from services.inception_svc import inception_svc
    return await inception_svc.create_session(
        llm_id=llm_id,
        thinking_mode=False,
        mode="create",
        template_id="unity_universal_2d",
    )


async def _read_session(session_id: str) -> dict:
    from infra.repo import crud
    return await crud.get_by_id("inception_sessions", session_id) or {}


async def _cleanup_session(session_id: str) -> None:
    if not session_id:
        return
    try:
        from infra.repo.sqlite_repo import get_db
        db = await get_db()
        await db.execute(
            "DELETE FROM inception_sessions WHERE id = ?", (session_id,),
        )
        await db.commit()
    except Exception:
        pass


# ── Audit ────────────────────────────────────────────────────────────


_DOC_KEYWORDS = (
    "设计文档", "风格指南", "qa报告", "qa 报告",
    "prd", "需求清单", "moodboard", "美术风格",
    "系统设计文档",
)


def _audit(draft: dict | None) -> list[str]:
    """Look for 'passed Pydantic but semantically broken' patterns."""
    issues: list[str] = []
    if not draft:
        return ["draft is empty"]

    tasks = draft.get("reviewed_tasks") or draft.get("atomic_tasks") or []
    contracts = draft.get("code_contracts") or []
    concept = draft.get("concept") or {}
    concept_text = json.dumps(concept, ensure_ascii=False) if concept else ""

    # 1. Pure-doc task (Phase 2/3 bug)
    for i, t in enumerate(tasks):
        if t.get("kind") == "final_qa":
            continue
        title = (t.get("title") or "")
        title_low = title.lower()
        if any(kw in title_low for kw in _DOC_KEYWORDS):
            issues.append(f"pure-doc task[{i}]: {title}")
            continue
        # Inspect output_schema for .md-only outputs
        schema = t.get("output_schema") or {}
        paths_desc = (
            schema.get("properties", {})
            .get("file_paths", {})
            .get("description")
            or ""
        ).lower()
        if paths_desc and (".md" in paths_desc or "markdown" in paths_desc):
            if not any(ext in paths_desc for ext in (
                ".cs", ".prefab", ".png", ".jpg", ".wav",
                ".unity", ".asset", ".fbx", ".anim",
            )):
                issues.append(f"doc-only schema task[{i}]: {title}")

    # 2. code_contract class name ≠ .cs filename stem
    for c in contracts:
        if not c:
            continue
        ti = c.get("task_index")
        cc = c.get("code_contract") or {}
        for f in cc.get("files") or []:
            stem = Path(f.get("path") or "").stem
            if not stem:
                continue
            for e in f.get("exports") or []:
                if e.get("kind") != "class":
                    continue
                sig = e.get("signature") or ""
                m = re.search(r"\bclass\s+(\w+)", sig)
                if not m:
                    continue
                cls = m.group(1)
                if cls != stem:
                    issues.append(
                        f"code_contract[task={ti}] class '{cls}' != "
                        f"file '{stem}.cs'"
                    )

    # 3. Audio assets but no AudioManager wiring
    has_audio_assets = any(
        ".wav" in (t.get("detail") or "")
        or ".wav" in (t.get("title") or "")
        for t in tasks
    )
    has_audio_mgr = any(
        "audiomanager" in ((t.get("detail") or "") + (t.get("title") or "")).lower()
        or "audiosource" in (t.get("detail") or "").lower()
        for t in tasks
    )
    if has_audio_assets and not has_audio_mgr:
        issues.append("有 .wav 资产但无 AudioManager / AudioSource 调用")

    # 4. Save / 高分
    needs_save = any(kw in concept_text for kw in ("高分", "存档", "进度"))
    has_save = any(
        kw in (t.get("detail") or "").lower()
        for t in tasks
        for kw in ("playerprefs", "savesystem", "save_data")
    ) or any("存档" in (t.get("detail") or "") for t in tasks)
    if needs_save and not has_save:
        issues.append("概念含高分/存档/进度，但无 PlayerPrefs/SaveSystem 任务")

    # 5. Scene transitions
    needs_scene = any(kw in concept_text for kw in ("主菜单", "重开", "过关", "结算", "游戏结束"))
    has_scene = any(
        kw in (t.get("detail") or "").lower()
        for t in tasks
        for kw in ("sceneloader", "scenemanager", "loadscene")
    )
    if needs_scene and not has_scene:
        issues.append("概念含主菜单/过关/重开，但无 SceneLoader/SceneManager 任务")

    return issues


# ── Single-run driver ───────────────────────────────────────────────


async def _run_one(idx: int, llm_id: str, timeout_s: float = 1800) -> dict:
    """Run one PM flow. Never raises — packages exceptions into result."""
    started = time.monotonic()
    session_id = ""
    try:
        from agents.sub_agents._planner_orchestrator import run_crew
        from services import planner_cache_svc

        session = await _create_session(llm_id)
        session_id = session["id"]

        result = await asyncio.wait_for(
            run_crew(session, PROMPT), timeout=timeout_s,
        )
        status = result.get("status", "unknown")
        error = result.get("error")
        failed_phase = result.get("failed_phase")
        draft = planner_cache_svc.get(session_id)
    except asyncio.TimeoutError:
        return {
            "idx": idx, "session_id": session_id,
            "status": "timeout",
            "elapsed_s": round(time.monotonic() - started, 2),
            "audit_issues": [],
        }
    except Exception as exc:
        return {
            "idx": idx, "session_id": session_id,
            "status": "exception",
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_s": round(time.monotonic() - started, 2),
            "audit_issues": [],
        }

    elapsed = round(time.monotonic() - started, 2)
    sess_row = await _read_session(session_id)

    return {
        "idx": idx,
        "session_id": session_id,
        "status": status,
        "error": error,
        "failed_phase": failed_phase,
        "elapsed_s": elapsed,
        "pm_runtime_s": sess_row.get("pending_runtime_seconds") or 0,
        "input_tokens": sess_row.get("pending_input_tokens") or 0,
        "output_tokens": sess_row.get("pending_output_tokens") or 0,
        "cost_cents": sess_row.get("pending_cost_cents") or 0,
        "audit_issues": _audit(draft) if status == "ready" else [],
        "draft_summary": (
            {
                "has_concept": bool(draft.get("concept")),
                "atomic_count": len(draft.get("atomic_tasks") or []),
                "reviewed_count": len(draft.get("reviewed_tasks") or []),
                "pathed_count": len(draft.get("pathed_tasks") or []),
                "contracts_count": sum(
                    1 for c in (draft.get("code_contracts") or [])
                    if c and c.get("code_contract")
                ),
            }
            if draft else {}
        ),
    }


# ── Report ──────────────────────────────────────────────────────────


def _format_cost(cents: int) -> str:
    if not cents:
        return "¥0"
    if cents < 100:
        return f"¥0.{cents:02d}"
    return f"¥{cents // 100}.{cents % 100:02d}"


def _format_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def _print_summary(results: list[dict]) -> None:
    n = len(results)
    if not n:
        print("\nno results.")
        return

    by_status: dict[str, int] = {}
    by_phase: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if r["status"] in ("failed", "exception", "timeout"):
            phase = r.get("failed_phase") or "(unknown)"
            by_phase[phase] = by_phase.get(phase, 0) + 1

    success = [r for r in results if r["status"] == "ready"]
    clean = [r for r in success if not r["audit_issues"]]
    flagged = [r for r in success if r["audit_issues"]]

    total_in = sum(r.get("input_tokens", 0) for r in results)
    total_out = sum(r.get("output_tokens", 0) for r in results)
    total_cost = sum(r.get("cost_cents", 0) for r in results)
    avg_elapsed = sum(r["elapsed_s"] for r in results) / n

    succ_elapsed = [r["elapsed_s"] for r in success]
    avg_succ = sum(succ_elapsed) / len(succ_elapsed) if succ_elapsed else 0

    pct = lambda c: f"{c*100//n}%" if n else "—"

    print()
    print("=" * 64)
    print(f"  Stress test results  ({n} runs)")
    print("=" * 64)
    print(f"  ✓ ready              : {len(success):>2}/{n} ({pct(len(success))})")
    print(f"     ├ clean (no audit) : {len(clean):>2}")
    print(f"     └ flagged          : {len(flagged):>2}")
    for s in ("failed", "exception", "timeout", "cancelled"):
        if by_status.get(s):
            glyph = {"failed": "✗", "exception": "💥",
                     "timeout": "⏱", "cancelled": "—"}[s]
            print(f"  {glyph} {s:18}: {by_status[s]:>2}/{n} ({pct(by_status[s])})")
    if by_phase:
        print()
        print("  Failure by phase:")
        for p, c in sorted(by_phase.items(), key=lambda kv: -kv[1]):
            print(f"    {p:24}: {c}")
    print()
    print(f"  Tokens (total)  : in {_format_tok(total_in):>8}  "
          f"out {_format_tok(total_out):>8}")
    print(f"  Cost (total)    : {_format_cost(total_cost)}")
    print(f"  Avg elapsed     : all={avg_elapsed:.1f}s  success-only={avg_succ:.1f}s")

    issue_counts: dict[str, int] = {}
    for r in success:
        for it in r["audit_issues"]:
            key = it.split(":")[0] if ":" in it else it
            issue_counts[key] = issue_counts.get(key, 0) + 1
    if issue_counts:
        print()
        print("  Audit issue patterns:")
        for k, c in sorted(issue_counts.items(), key=lambda kv: -kv[1]):
            print(f"    {k:50}: {c}")

    # Failure messages (top 5 distinct)
    fail_msgs: dict[str, int] = {}
    for r in results:
        if r["status"] != "ready" and r.get("error"):
            # truncate so similar errors group
            key = (r["error"] or "")[:80]
            fail_msgs[key] = fail_msgs.get(key, 0) + 1
    if fail_msgs:
        print()
        print("  Top failure messages (first 80 chars):")
        for k, c in sorted(fail_msgs.items(), key=lambda kv: -kv[1])[:5]:
            print(f"    [{c}x] {k}")

    print()


# ── Entry ───────────────────────────────────────────────────────────


async def amain(args: argparse.Namespace) -> None:
    llm_id = await _resolve_llm_id()
    print(f"Using LLM: {llm_id}")
    print(f"Running {args.runs} PM flows with concurrency={args.concurrency}…")
    print()

    sem = asyncio.Semaphore(args.concurrency)
    completed = 0
    completed_lock = asyncio.Lock()

    async def bounded(idx: int) -> dict:
        nonlocal completed
        async with sem:
            r = await _run_one(idx, llm_id, timeout_s=args.timeout)
        async with completed_lock:
            completed += 1
            glyph = {"ready": "✓", "failed": "✗", "exception": "💥",
                     "timeout": "⏱", "cancelled": "—"}.get(r["status"], "?")
            audit_note = (
                f"  +{len(r['audit_issues'])}审计问题"
                if r["audit_issues"] else ""
            )
            err = ""
            if r["status"] != "ready":
                e = r.get("failed_phase") or r.get("error") or ""
                err = f"  {str(e)[:50]}"
            print(
                f"  [{completed:>2}/{args.runs}] {glyph} #{idx:>2} "
                f"{r['status']:<10} "
                f"{r['elapsed_s']:>6.1f}s "
                f"in={_format_tok(r.get('input_tokens', 0)):>6} "
                f"out={_format_tok(r.get('output_tokens', 0)):>6} "
                f"cost={_format_cost(r.get('cost_cents', 0)):>7}"
                f"{audit_note}{err}"
            )
        return r

    results = await asyncio.gather(*[bounded(i) for i in range(args.runs)])

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  Full per-run report → {out_path}")

    _print_summary(results)

    if not args.keep_sessions:
        for r in results:
            await _cleanup_session(r.get("session_id", ""))
        print(f"  Cleaned up {len(results)} test session rows.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--timeout", type=float, default=1800,
        help="Per-run timeout in seconds (default 1800 = 30 min).",
    )
    parser.add_argument(
        "--output", type=str,
        default="scripts/stress_test_pm_report.json",
    )
    parser.add_argument(
        "--keep-sessions", action="store_true",
        help="Don't delete the stress-test inception_session rows.",
    )
    args = parser.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
