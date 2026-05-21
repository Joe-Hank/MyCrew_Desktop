"""/diagnose Phase 4 — variant probe.

Bug: Qwen + Task(output_pydantic=Spec) — agent emits valid ExecutorOutput
without ever calling tools to actually write the files it claims.

Integration test (diag_layer1_layer2) already showed Scenario B: 0/5
trials wrote files (tools list empty, captured was clean Spec, files
absent on disk).

This probe tests 4 hypotheses by varying ONE thing at a time. Each
variant runs N=5 trials in "files missing initially" mode (which is
the actual production failure scenario), measuring tool fire rate +
disk truth pass rate.

Variants:
  - baseline   : current production config (output_pydantic=Spec,
                 mild prompt about verify_outputs)
  - strong_prompt (H2): same but with aggressive "MUST call tools before Spec"
                 language in backstory + description
  - high_iter  (H3): baseline but max_iter=8 (vs current 3)
  - simple_tool (H5): baseline but using simple write_file tool (not
                 Unity-MCP-shaped create_script)
  - no_pydantic (H1): drop output_pydantic, use plain Task + ask agent
                 to call verify_outputs as the terminator

Pass criterion: tools fired AND all files on disk → 'real success'

Run:
  backend/.venv/Scripts/python.exe scripts/diag_phase4_variants.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent.parent
TRIALS_PER_VARIANT = 5

EXPECTED_PATHS = [
    "Assets/Scripts/MouseSlicer.cs",
    "Assets/Scripts/FruitSpawner.cs",
]


def load_qwen() -> tuple[str, str]:
    db = sqlite3.connect(str(ROOT / "data" / "db" / "mycrew.db"))
    db.row_factory = sqlite3.Row
    r = db.execute(
        "SELECT base_url, api_key_ref FROM llm_providers WHERE name='Qwen'",
    ).fetchone()
    db.close()
    return r["base_url"], r["api_key_ref"]


async def run_trial(variant: str, base_url: str, api_key: str,
                    project_root: Path) -> dict:
    """One Crew kickoff with the given variant config."""
    from crewai import Agent, Crew, Process, Task, LLM
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field
    from domain.crew_specs import ExecutorOutput
    from src.tools.builtin.local.verify_outputs import make_verify_outputs_tool

    if api_key:
        os.environ["DASHSCOPE_API_KEY"] = api_key

    fired_tools: list[str] = []

    # ── Tool definitions per variant ──────────────────────────────
    class WriteFileArgs(BaseModel):
        path: str = Field(description="Relative path under project root")
        content: str = Field(description="File content (full text)")

    class WriteFileTool(BaseTool):
        name: str = "write_file"
        description: str = "Write text content to a file path (creates parent directories)."
        args_schema: type[BaseModel] = WriteFileArgs
        def _run(self, path: str, content: str) -> str:
            fired_tools.append("write_file")
            abs_path = (project_root / path
                        if not Path(path).is_absolute() else Path(path))
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            return f"OK — wrote {len(content)} bytes to {path}"

    class CreateScriptArgs(BaseModel):
        path: str = Field(description="Relative .cs path under project root")
        class_name: str = Field(description="Public class name")
        namespace: str = Field(default="", description="Optional namespace")
        body: str = Field(description="Full C# class body including using statements")

    class CreateScriptTool(BaseTool):
        name: str = "create_script"
        description: str = (
            "Create a Unity C# script with the given class. "
            "Writes 'using UnityEngine;\\n...class declaration { body }' to path."
        )
        args_schema: type[BaseModel] = CreateScriptArgs
        def _run(self, path: str, class_name: str, namespace: str = "",
                 body: str = "") -> str:
            fired_tools.append("create_script")
            abs_path = (project_root / path
                        if not Path(path).is_absolute() else Path(path))
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            content = body if body else (
                f"using UnityEngine;\n"
                + (f"namespace {namespace} {{ " if namespace else "")
                + f"public class {class_name} : MonoBehaviour {{}}"
                + (" }" if namespace else "")
            )
            abs_path.write_text(content, encoding="utf-8")
            return f"OK — created {path} with class {class_name}"

    vo_wrapper = make_verify_outputs_tool(
        project_root=str(project_root), expected_paths=EXPECTED_PATHS,
    )
    class VerifyOutputsTracker(BaseTool):
        name: str = "verify_outputs"
        description: str = vo_wrapper.description
        args_schema: type[BaseModel] = vo_wrapper.args_schema
        def _run(self, file_paths: list[str]) -> str:
            fired_tools.append("verify_outputs")
            return vo_wrapper._run(file_paths)

    # ── Variant-specific config ──────────────────────────────────
    use_simple_tool = (variant == "simple_tool")
    use_no_pydantic = (variant == "no_pydantic")
    max_iter = 8 if variant == "high_iter" else 3
    strong_prompt = (variant == "strong_prompt")

    tools = [VerifyOutputsTracker()]
    if use_simple_tool:
        tools.append(WriteFileTool())
    else:
        tools.append(CreateScriptTool())
        tools.append(WriteFileTool())  # also have write_file in non-simple variants

    llm = LLM(model="dashscope/qwen-plus", api_key=api_key,
              base_url=base_url, is_litellm=True)

    if strong_prompt:
        backstory = (
            "你是 System Implementation Crew 的实装 Executor。\n\n"
            "**TOOL USE PROTOCOL — 不可违反**：\n"
            "1. **禁止**在没有调用 create_script (或 write_file) 把 file_paths 列表里"
            "**每一个**文件真写到磁盘之前产出任何 JSON / Spec / 结构化输出。\n"
            "2. 每写完一个文件就立即调一次 verify_outputs(file_paths=[已写完的所有])。\n"
            "3. verify_outputs 返回 OK 才能产出最终 ExecutorOutput。\n"
            "4. **如果你跳过 (1) 直接产 JSON，server-side disk truth check 会判 fail，"
            "整个 task 失败，你的工作作废**。这不是建议，是硬约束。"
        )
        description_extra = (
            "\n\n**警告（严格按此执行）**：\n"
            "你的输出会被 server-side 检查每个 file_paths 是否真在磁盘上。"
            "不写文件就编 JSON = task 失败。**先 create_script，再 verify_outputs，"
            "最后才 ExecutorOutput**。"
        )
    else:
        backstory = (
            "System Implementation Crew 的实装 Executor。流程：\n"
            "(1) 用 create_script 或 write_file 把每个 .cs 文件写到磁盘；\n"
            "(2) **必须**调一次 verify_outputs(file_paths=[...]) 自检；\n"
            "(3) 通过后再产出 ExecutorOutput JSON。"
        )
        description_extra = ""

    agent = Agent(
        role="Unity Developer",
        goal="实装两个 C# 脚本并最终输出 ExecutorOutput 结构化结果。",
        backstory=backstory,
        llm=llm,
        tools=tools,
        max_iter=max_iter,
        verbose=False,
        allow_delegation=False,
    )

    description = (
        "## 任务：实装两个脚本\n\n"
        f"项目根目录：`{project_root}`\n\n"
        "你必须产出以下两个文件，路径都是相对项目根的：\n"
        + "\n".join(f"  - {p}" for p in EXPECTED_PATHS)
        + "\n\n两个脚本都是 MonoBehaviour 子类，简单骨架即可。"
        + description_extra
    )

    task_kwargs = {
        "description": description,
        "expected_output": (
            "ExecutorOutput JSON: file_paths, coverage, summary."
            if not use_no_pydantic else
            "Final answer (text) confirming both files written."
        ),
        "agent": agent,
    }
    if not use_no_pydantic:
        task_kwargs["output_pydantic"] = ExecutorOutput
    task = Task(**task_kwargs)

    crew = Crew(agents=[agent], tasks=[task],
                process=Process.sequential, verbose=False)

    err = None
    pydantic_obj = None
    try:
        result = crew.kickoff()
        task_output = task.output
        if task_output is not None:
            pydantic_obj = getattr(task_output, "pydantic", None)
    except Exception as exc:
        err = f"{type(exc).__name__}: {str(exc)[:200]}"

    # Disk truth
    on_disk = [
        p for p in EXPECTED_PATHS
        if (project_root / p).exists()
        and (project_root / p).stat().st_size > 0
    ]
    write_calls = sum(1 for t in fired_tools if t in ("write_file", "create_script"))
    return {
        "variant": variant,
        "error": err,
        "pydantic_ok": pydantic_obj is not None,
        "fired_tools": fired_tools,
        "n_write_calls": write_calls,
        "verify_called": "verify_outputs" in fired_tools,
        "n_files_on_disk": len(on_disk),
        "real_success": (
            len(on_disk) == len(EXPECTED_PATHS)
            and (pydantic_obj is not None or use_no_pydantic)
            and err is None
        ),
    }


async def main():
    base_url, api_key = load_qwen()
    print(f"/diagnose Phase 4 — Qwen variant probe (N={TRIALS_PER_VARIANT}/variant)\n")

    variants = [
        "baseline",
        "strong_prompt",
        "high_iter",
        "simple_tool",
        "no_pydantic",
    ]
    all_results = {}
    for variant in variants:
        print(f"{'=' * 70}\n  Variant: {variant}\n{'=' * 70}")
        trials = []
        for i in range(TRIALS_PER_VARIANT):
            td = Path(tempfile.mkdtemp(prefix=f"diag_{variant}_"))
            r = await run_trial(variant, base_url, api_key, td)
            trials.append(r)
            ok = "✓" if r["real_success"] else "✗"
            print(f"  Trial {i+1}: {ok}  write_calls={r['n_write_calls']}  "
                  f"verify={'✓' if r['verify_called'] else '✗'}  "
                  f"on_disk={r['n_files_on_disk']}/{len(EXPECTED_PATHS)}  "
                  f"tools={r['fired_tools'][:5]}{'...' if len(r['fired_tools']) > 5 else ''}")
            if r["error"]:
                print(f"    err: {r['error']}")
        all_results[variant] = trials

    # ── Tally ──────────────────────────────────────────────────────
    print(f"\n{'#' * 70}\n  TALLY\n{'#' * 70}")
    print(f"\n  {'variant':16} {'real_success':12} {'wrote_files':12} {'verify_called':14}")
    print("  " + "-" * 60)
    for variant in variants:
        trials = all_results[variant]
        n = len(trials)
        rs = sum(1 for t in trials if t["real_success"])
        wf = sum(1 for t in trials if t["n_write_calls"] > 0)
        vc = sum(1 for t in trials if t["verify_called"])
        print(f"  {variant:16} {rs:>2}/{n}         {wf:>2}/{n}         {vc:>2}/{n}")

    # Pick winner
    by_rs = sorted(all_results.items(),
                   key=lambda x: -sum(1 for t in x[1] if t["real_success"]))
    print(f"\n  Winning variant by real_success: {by_rs[0][0]} "
          f"({sum(1 for t in by_rs[0][1] if t['real_success'])}/{TRIALS_PER_VARIANT})")

    out = ROOT / "data" / "diag_phase4_variants.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(f"\n  Full results: {out}")


if __name__ == "__main__":
    asyncio.run(main())
