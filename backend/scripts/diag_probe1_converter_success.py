"""Layer 0 / Probe 1: CrewAI 1.14 Task(output_pydantic=Spec) 首次 Converter
成功率实测。这是整个架构重构方案的 gate。

设计：
  - 用真实 executor 级别的 task description（带 code_contract 风格的 spec）
  - 11 工具上下文（emit_output 形态的 verify_outputs mock + 10 Unity tool mocks）
  - Task(output_pydantic=ExecutorSpec) — 框架接管 schema
  - 不挂 emit_output 工具，强迫 Converter 走完整路径
  - 每个 provider N=10 trials
  - 测量：
    * task.output.pydantic 非 None 率（最终成功）
    * 第一次 LLM 响应即合 schema 率（Converter 无需重试）
    * 总 LLM call 数分布（看 Converter 重试次数）

判定：
  ≥ 90% → Layer 1 OK 推进
  70-90% → 推进但需要自定义 retry prompt 注入上游
  <70% → 推翻 Layer 1，必须保留工具范式

Run:
  backend/.venv/Scripts/python.exe scripts/diag_probe1_converter_success.py
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import traceback
from pathlib import Path
from typing import Literal

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent.parent
TRIALS = 10

# (db_provider_name, litellm_prefix, model_name)
VARIANTS = [
    ("Qwen",     "dashscope", "qwen-plus"),
    ("DeepSeek", "deepseek",  "deepseek-v4-flash"),
]


def load_provider(name: str) -> tuple[str, str]:
    db = sqlite3.connect(str(ROOT / "data" / "db" / "mycrew.db"))
    db.row_factory = sqlite3.Row
    r = db.execute(
        "SELECT base_url, api_key_ref FROM llm_providers WHERE name=?", (name,),
    ).fetchone()
    db.close()
    if not r:
        raise SystemExit(f"Provider {name!r} not found in DB.")
    return r["base_url"], r["api_key_ref"]


def load_production_task() -> dict:
    """Reuse the failing executor input from fruit-ninja for realism."""
    p = (
        ROOT
        / "output" / "proj_9280b9f71422"
        / "task_208e6857bf1f" / "sub" / "1_executor_in.json"
    )
    return json.loads(p.read_text(encoding="utf-8"))


# ── Tracer ────────────────────────────────────────────────────────────

LLM_CALL_COUNTS: dict[int, int] = {}  # trial idx -> call count


def install_litellm_tracer():
    """Count LiteLLM calls per trial so we can see how many Converter retries
    actually happen."""
    import litellm
    orig_async = litellm.acompletion
    orig_sync = litellm.completion
    current_trial = [0]

    async def traced_a(**kwargs):
        LLM_CALL_COUNTS[current_trial[0]] = LLM_CALL_COUNTS.get(current_trial[0], 0) + 1
        return await orig_async(**kwargs)

    def traced_s(**kwargs):
        LLM_CALL_COUNTS[current_trial[0]] = LLM_CALL_COUNTS.get(current_trial[0], 0) + 1
        return orig_sync(**kwargs)

    litellm.acompletion = traced_a
    litellm.completion = traced_s
    return current_trial


# ── Probe ─────────────────────────────────────────────────────────────


async def run_trial(trial_idx: int, current_trial_holder: list,
                    base_url: str, api_key: str,
                    prefix: str, model: str,
                    prod_task: dict) -> dict:
    """One Crew kickoff with output_pydantic — return outcome."""
    from crewai import Agent, Crew, Process, Task, LLM
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field

    current_trial_holder[0] = trial_idx
    LLM_CALL_COUNTS[trial_idx] = 0

    # ExecutorSpec mirrors the planned Layer 1 schema
    class ExecutorSpec(BaseModel):
        """Final structured output for an executor step."""
        file_paths: list[str] = Field(
            description="Paths of files this step produced (relative to project root).",
        )
        coverage: dict[str, int] = Field(
            default_factory=dict,
            description="Per-file count of contract signatures implemented.",
        )
        summary: str = Field(
            default="",
            description="One-line summary of what was done.",
        )

    llm = LLM(
        model=f"{prefix}/{model}",
        api_key=api_key,
        base_url=base_url,
        is_litellm=True,
    )

    # Mock tool set: same shape as fruit-ninja Unity Developer (no emit_output —
    # we're testing whether Converter alone can produce structured output).
    class UnityInput(BaseModel):
        action: str = Field(description="Action name")
        target: str | None = Field(default=None, description="Target path")
        params: dict = Field(default_factory=dict, description="Params")

    class UnityNoop(BaseTool):
        name: str = "noop"
        description: str = "Unity MCP noop tool"
        args_schema: type[BaseModel] = UnityInput
        def _run(self, action: str, target: str | None = None,
                 params: dict | None = None) -> str:
            return json.dumps({"ok": True, "tool": self.name, "action": action})

    tool_names = [
        "create_script", "script_apply_edits", "apply_text_edits", "find_in_file",
        "validate_script", "refresh_unity", "manage_gameobject", "manage_components",
        "set_property", "manage_asset",
    ]
    tools = [
        UnityNoop(name=n, description=f"Unity MCP tool: {n}")
        for n in tool_names
    ]

    description = (
        "## 任务: 实现 MouseSlicer.cs（mock，无需真创建文件）\n\n"
        + prod_task.get("step_instructions", "")
        + "\n\n## Head Spec (prev_step_payload)\n```json\n"
        + json.dumps(prod_task.get("prev_step_payload", {}), ensure_ascii=False, indent=2)[:2500]
        + "\n```\n\n"
        + "**注意（mock 诊断模式）**：所有 Unity 工具都是 noop，你只需调 1-2 个"
        + "合理工具走通流程，**不需要真创建文件**。"
    )

    agent = Agent(
        role="Unity Developer",
        goal="按 Head spec 实装 C# 脚本，最后产出 ExecutorSpec 结构化结果。",
        backstory=(
            "你是 System Implementation Crew 的实装 Executor。流程："
            "(1) create_script 建骨架；(2) script_apply_edits 实装契约签名；"
            "(3) find_in_file 自审；(4) 给出 ExecutorSpec 形态的最终输出。"
        ),
        llm=llm,
        tools=tools,
        max_iter=3,
        verbose=False,
        allow_delegation=False,
    )

    task = Task(
        description=description,
        expected_output=(
            "ExecutorSpec JSON: file_paths (list[str]), "
            "coverage (dict[str, int]), summary (str)."
        ),
        agent=agent,
        output_pydantic=ExecutorSpec,
    )
    crew = Crew(
        agents=[agent], tasks=[task],
        process=Process.sequential, verbose=False,
    )

    err = None
    raw_text = ""
    pydantic_obj = None
    json_dict = None
    try:
        result = crew.kickoff()
        # CrewOutput exposes tasks_output - check the task's output
        task_output = task.output
        if task_output is not None:
            pydantic_obj = getattr(task_output, "pydantic", None)
            json_dict = getattr(task_output, "json_dict", None)
            raw_text = getattr(task_output, "raw", "") or str(result)
        else:
            raw_text = str(result)
    except Exception as exc:
        err = f"{type(exc).__name__}: {str(exc)[:300]}"

    n_calls = LLM_CALL_COUNTS.get(trial_idx, 0)
    return {
        "trial": trial_idx,
        "error": err,
        "pydantic_ok": pydantic_obj is not None,
        "pydantic_dump": pydantic_obj.model_dump() if pydantic_obj else None,
        "json_dict": json_dict,
        "raw_head": raw_text[:300],
        "n_llm_calls": n_calls,
    }


async def main():
    install_litellm_tracer()
    prod_task = load_production_task()
    print(f"Probe 1: CrewAI Converter first-call success rate")
    print(f"Trials per variant: {TRIALS}\n")

    # CrewAI Converter / InternalInstructor calls LiteLLM through a path
    # that does NOT inherit api_key/base_url from the LLM instance — it
    # relies on env vars. Bridge both keys before kickoff so the Probe can
    # actually test what we care about (Converter success rate) rather
    # than fail on credentials.
    #
    # NOTE: This is a probe-only workaround. Production should solve this
    # by either (a) monkey-patching Converter to pass kwargs, or (b)
    # setting env at backend startup. Discovery itself is informative —
    # see Probe 1 verdict report.
    import os
    qwen_base, qwen_key = load_provider("Qwen")
    ds_base, ds_key = load_provider("DeepSeek")
    if qwen_key:
        os.environ["DASHSCOPE_API_KEY"] = qwen_key
    if ds_key:
        os.environ["DEEPSEEK_API_KEY"] = ds_key
    print(f"  (DASHSCOPE_API_KEY / DEEPSEEK_API_KEY set in env as workaround)")

    holder = [0]  # mutable trial index for tracer
    # patch tracer to use holder
    import litellm
    orig_async = litellm.acompletion
    orig_sync = litellm.completion
    async def traced_a(**kwargs):
        LLM_CALL_COUNTS[holder[0]] = LLM_CALL_COUNTS.get(holder[0], 0) + 1
        return await orig_async(**kwargs)
    def traced_s(**kwargs):
        LLM_CALL_COUNTS[holder[0]] = LLM_CALL_COUNTS.get(holder[0], 0) + 1
        return orig_sync(**kwargs)
    litellm.acompletion = traced_a
    litellm.completion = traced_s

    all_results = {}
    for name, prefix, model in VARIANTS:
        base_url, api_key = load_provider(name)
        print(f"{'=' * 70}\n  {name}  /  {prefix}/{model}\n{'=' * 70}")
        results = []
        for i in range(TRIALS):
            trial_global_idx = len(results) + (1000 if name == "DeepSeek" else 0)
            r = await run_trial(
                trial_global_idx, holder,
                base_url, api_key, prefix, model, prod_task,
            )
            results.append(r)
            ok = "✓" if r["pydantic_ok"] else ("ERR" if r["error"] else "✗")
            print(f"  Trial {i+1}/{TRIALS}: {ok}  n_calls={r['n_llm_calls']}  "
                  f"pydantic={'OK' if r['pydantic_ok'] else 'NO'}  "
                  f"json_dict={'OK' if r['json_dict'] else 'NO'}  "
                  f"err={r['error']!r}"[:200])
            if not r["pydantic_ok"]:
                print(f"     raw_head: {r['raw_head']!r}")
        all_results[name] = results

    # ── Tally ─────────────────────────────────────────────────────────
    print(f"\n{'#' * 70}\n  TALLY\n{'#' * 70}")
    for name, trials in all_results.items():
        n = len(trials)
        py_ok = sum(1 for t in trials if t["pydantic_ok"])
        jd_ok = sum(1 for t in trials if t["json_dict"])
        errs = sum(1 for t in trials if t["error"])
        # First-call success = exactly 1 LLM call AND pydantic populated
        first_ok = sum(1 for t in trials
                       if t["pydantic_ok"] and t["n_llm_calls"] == 1)
        call_counts = [t["n_llm_calls"] for t in trials]
        avg_calls = sum(call_counts) / max(len(call_counts), 1)
        print(f"\n  {name}:")
        print(f"    pydantic_ok        : {py_ok}/{n}")
        print(f"    json_dict_ok       : {jd_ok}/{n}")
        print(f"    first-call success : {first_ok}/{n}  (1 LLM call AND pydantic OK)")
        print(f"    errors             : {errs}/{n}")
        print(f"    avg LLM calls/trial: {avg_calls:.1f}")
        print(f"    call counts dist   : {sorted(call_counts)}")

        # Verdict
        rate = py_ok / n
        if rate >= 0.9:
            print(f"    → VERDICT: ≥90% — Layer 1 推进")
        elif rate >= 0.7:
            print(f"    → VERDICT: 70-90% — 推进但需自定义 retry prompt")
        else:
            print(f"    → VERDICT: <70% — Layer 1 不可推进，需要重新设计")

    out = ROOT / "data" / "diag_probe1_results.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n  Full results: {out}")


if __name__ == "__main__":
    asyncio.run(main())
