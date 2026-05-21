"""Verify whether reverting bfb4ae9 (is_litellm=False, native CrewAI path)
re-introduces the 'DSML leak' bug it was originally written to avoid.

For Bug B in fruit-ninja (proj_9280b9f71422): commit bfb4ae9 forced
is_litellm=True to dodge a claimed CrewAI 1.14 native-deepseek bug
where tool calls leaked as text into message.content. Earlier
reproducers (diag_crewai_executor_repro.py) showed that with realistic
load, is_litellm=True actually breaks because CrewAI falls back to
ReAct text parsing that deepseek-reasoner sometimes mis-formats.

This script runs the SAME production-grade setup N times under each
flag and tallies:
  - tool_fired       : at least one tool invocation observed
  - clean_output     : no 'Action:' / '<tool_call>' / fenced JSON in
                       the final agent text (= no leak / no malformed
                       ReAct echo)
  - leaks_action     : final text contains 'Action: <name>' but no
                       tool was fired (= ReAct format parsed wrong)
  - leaks_json_block : final text contains a ```json block that looks
                       like a tool call (= DSML-like leak)

Run from backend/:
    backend/.venv/Scripts/python.exe scripts/diag_native_vs_litellm.py
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import sys
import traceback
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent.parent
TRIALS_PER_VARIANT = 5

# Override via env: DIAG_MODEL=deepseek-chat (non-reasoner) to test
# whether the reasoner variant is the actual culprit for emit_output
# not firing.
import os as _os
MODEL_OVERRIDE = _os.environ.get("DIAG_MODEL", "deepseek-v4-flash")
# Only run the variants listed; default to both, env to filter.
VARIANTS_ENV = _os.environ.get("DIAG_VARIANTS", "native_path,litellm_path")
# Which provider row to load credentials from (matches llm_providers.name).
PROVIDER_NAME = _os.environ.get("DIAG_PROVIDER", "DeepSeek")
# LiteLLM provider prefix (qwen->dashscope, custom->openai, openai->openai, etc.)
# Mirrors crewai_runner._build_litellm_model_string.
PROVIDER_PREFIX = _os.environ.get("DIAG_PREFIX", "deepseek")

# Sample 10 representative Unity tools that the production Unity
# Developer agent has access to — enough to push tool-count past the
# point where format confusion happens, without burning 30+ tool
# schemas of context each trial.
UNITY_TOOLS_SAMPLE = [
    "create_script", "script_apply_edits", "apply_text_edits", "find_in_file",
    "validate_script", "refresh_unity", "manage_gameobject", "manage_components",
    "set_property", "manage_asset",
]


def load_provider() -> tuple[str, str]:
    db = sqlite3.connect(str(ROOT / "data" / "db" / "mycrew.db"))
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute(
        "SELECT base_url, api_key_ref FROM llm_providers WHERE name=?",
        (PROVIDER_NAME,),
    )
    r = cur.fetchone()
    db.close()
    if not r:
        raise SystemExit(f"Provider '{PROVIDER_NAME}' not found in DB.")
    return r["base_url"], r["api_key_ref"]


def load_production_task() -> dict:
    """Read the actual failing executor step's input."""
    p = (
        ROOT
        / "output" / "proj_9280b9f71422"
        / "task_208e6857bf1f" / "sub" / "1_executor_in.json"
    )
    return json.loads(p.read_text(encoding="utf-8"))


def classify(final_text: str, tool_was_called: bool) -> dict:
    """Score one trial's outcome."""
    t = final_text or ""
    has_action = bool(re.search(r"\bAction:\s*\w+", t))
    has_json_block = bool(re.search(r"```json\s*\{", t, re.IGNORECASE))
    has_tool_call_tag = bool(re.search(r"<\s*tool_call|</?tool_call|<\|tool", t))
    leaks_action = has_action and not tool_was_called
    leaks_json_block = has_json_block and not tool_was_called
    leaks_dsml = has_tool_call_tag
    clean = (not has_action and not has_json_block and not has_tool_call_tag)
    return {
        "tool_fired": tool_was_called,
        "clean_output": clean,
        "leaks_action": leaks_action,
        "leaks_json_block": leaks_json_block,
        "leaks_dsml": leaks_dsml,
        "has_action": has_action,
        "has_json_block": has_json_block,
        "final_text_head": t[:300],
    }


async def run_one_trial(*, base_url: str, api_key: str, is_litellm: bool,
                        prod_task: dict) -> dict:
    """Spin up an isolated CrewAI Agent + tools and kickoff once.

    Each trial gets a fresh Agent so reasoning_content state doesn't
    bleed between runs.
    """
    from crewai import Agent, Crew, Process, Task, LLM
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field

    llm = LLM(
        model=f"{PROVIDER_PREFIX}/{MODEL_OVERRIDE}",
        api_key=api_key,
        base_url=base_url,
        is_litellm=is_litellm,
    )

    # Track every tool call across the trial.
    fired_tools: list[str] = []

    class EmitInput(BaseModel):
        payload: dict = Field(description="Output payload")

    class EmitOutputMock(BaseTool):
        name: str = "emit_output"
        description: str = "Submit your final structured output. Required at end."
        args_schema: type[BaseModel] = EmitInput
        def _run(self, payload: dict) -> str:
            fired_tools.append("emit_output")
            return json.dumps({"ok": True, "captured": payload}, ensure_ascii=False)

    class UnityInput(BaseModel):
        action: str = Field(description="Action name within this Unity tool")
        target: str | None = Field(default=None, description="Target object/asset")
        params: dict = Field(default_factory=dict, description="Action parameters")

    class UnityMockTool(BaseTool):
        name: str = "noop"
        description: str = "Unity MCP tool"
        args_schema: type[BaseModel] = UnityInput
        def _run(self, action: str, target: str | None = None,
                 params: dict | None = None) -> str:
            fired_tools.append(self.name)
            return json.dumps({"ok": True, "tool": self.name, "action": action})

    tools = [EmitOutputMock()]
    for n in UNITY_TOOLS_SAMPLE:
        tools.append(UnityMockTool(name=n,
            description=f"Unity MCP tool: {n}. Supports actions like create/read/modify."))

    # Mirror seed_crews:639-650 instructions verbatim.
    description = (
        "## 任务: " + prod_task.get("step_instructions", "")[:50] + "\n\n"
        + prod_task.get("step_instructions", "") + "\n\n"
        + "## prev_step_payload\n```json\n"
        + json.dumps(prod_task.get("prev_step_payload", {}), ensure_ascii=False, indent=2)[:3000]
        + "\n```\n"
    )

    agent = Agent(
        role="Unity Developer",
        goal="按 PM code_contract + Head spec 实装 C# 脚本，最后调 emit_output 报告。",
        backstory=(
            "System Impl / UI Impl Crew 的实装 Executor。"
            "工作流程：(1) 用 create_script 建骨架；"
            "(2) script_apply_edits 实现契约；"
            "(3) find_in_file 自审；"
            "(4) 调 emit_output 报告 file_paths + coverage。"
            "**Mock 模式说明（本次诊断）**：所有 Unity 工具都是 noop，你只需选择 1-2 个"
            "合理工具走通流程，最后必须真正调用 emit_output 提交结果。"
        ),
        llm=llm,
        tools=tools,
        max_iter=3,
        verbose=False,
        allow_delegation=False,
    )

    task = Task(
        description=description,
        expected_output="emit_output 工具的返回值。",
        agent=agent,
    )
    crew = Crew(
        agents=[agent], tasks=[task],
        process=Process.sequential, verbose=False,
    )

    err = None
    final = ""
    try:
        result = crew.kickoff()
        final = str(result)
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()

    return {
        "fired_tools": fired_tools,
        "final_text": final,
        "error": err,
        **classify(final, bool(fired_tools)),
    }


async def main() -> None:
    base_url, api_key = load_provider()
    prod_task = load_production_task()
    print(f"Provider: {base_url}  key={api_key[:10]}...")
    print(f"Trials per variant: {TRIALS_PER_VARIANT}")
    print(f"Tools attached: {len(UNITY_TOOLS_SAMPLE)+1} (emit_output + {len(UNITY_TOOLS_SAMPLE)} unity)")

    print(f"Model under test: deepseek/{MODEL_OVERRIDE}")
    selected = set(v.strip() for v in VARIANTS_ENV.split(","))
    print(f"Variants enabled: {selected}")
    all_results = {}
    variant_pool = [("native_path", False), ("litellm_path", True)]
    for variant_name, is_litellm in [v for v in variant_pool if v[0] in selected]:
        print(f"\n{'=' * 70}\n  Variant: {variant_name}  (is_litellm={is_litellm})\n{'=' * 70}")
        trials = []
        for i in range(TRIALS_PER_VARIANT):
            print(f"\n--- Trial {i+1}/{TRIALS_PER_VARIANT} ---")
            r = await run_one_trial(
                base_url=base_url, api_key=api_key,
                is_litellm=is_litellm, prod_task=prod_task,
            )
            trials.append(r)
            print(f"  tool_fired={r['tool_fired']}  clean={r['clean_output']}  "
                  f"leaks_action={r['leaks_action']}  leaks_json_block={r['leaks_json_block']}  "
                  f"leaks_dsml={r['leaks_dsml']}")
            print(f"  fired_tools={r['fired_tools']}")
            print(f"  final_head={r['final_text_head']!r}")
            if r["error"]:
                print(f"  ERROR: {r['error']}")
        all_results[variant_name] = trials

    print(f"\n{'#' * 70}\n  TALLY\n{'#' * 70}")
    for variant_name, trials in all_results.items():
        n = len(trials)
        fired = sum(1 for t in trials if t["tool_fired"])
        clean = sum(1 for t in trials if t["clean_output"])
        leak_act = sum(1 for t in trials if t["leaks_action"])
        leak_js = sum(1 for t in trials if t["leaks_json_block"])
        leak_dsml = sum(1 for t in trials if t["leaks_dsml"])
        errs = sum(1 for t in trials if t["error"])
        print(f"\n  {variant_name}:")
        print(f"    tool_fired       : {fired}/{n}")
        print(f"    clean_output     : {clean}/{n}")
        print(f"    leaks_action     : {leak_act}/{n}  (Action: prefix but tool not fired)")
        print(f"    leaks_json_block : {leak_js}/{n}  (```json block but tool not fired)")
        print(f"    leaks_dsml       : {leak_dsml}/{n}  (<tool_call> tag in text)")
        print(f"    errors           : {errs}/{n}")

    # Save full results for offline inspection (one file per model so
    # runs against different models don't clobber each other).
    out = ROOT / "data" / f"diag_native_vs_litellm_{PROVIDER_PREFIX}_{MODEL_OVERRIDE.replace('/', '_')}.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2,
                              default=str), encoding="utf-8")
    print(f"\nFull results: {out}")


if __name__ == "__main__":
    asyncio.run(main())
