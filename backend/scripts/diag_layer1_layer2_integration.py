"""Layer 1 + Layer 2 integration test (2026-05-21).

End-to-end validation that:
  - Task(output_pydantic=ExecutorOutput) coerces agent output into Spec
  - verify_outputs is injected and accessible to the agent
  - Agent can self-correct when verify_outputs reports missing files
  - Final captured payload has correct shape

Scenarios (each N=5 trials):
  A. Files already exist     → agent should verify and return Spec straight
  B. Files missing initially → agent must call write_file, then verify, then return

Provider: Qwen-plus (Probe 1 winner).

Run:
  backend/.venv/Scripts/python.exe scripts/diag_layer1_layer2_integration.py
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
TRIALS_PER_SCENARIO = 5
EXPECTED_PATHS = [
    "Assets/Scripts/MouseSlicer.cs",
    "Assets/Scripts/FruitSpawner.cs",
]


def load_provider(name: str) -> tuple[str, str]:
    db = sqlite3.connect(str(ROOT / "data" / "db" / "mycrew.db"))
    db.row_factory = sqlite3.Row
    r = db.execute(
        "SELECT base_url, api_key_ref FROM llm_providers WHERE name=?", (name,),
    ).fetchone()
    db.close()
    return r["base_url"], r["api_key_ref"]


def setup_temp_project(populate_files: bool) -> Path:
    """Make a temp project_root. If populate_files=True, write the
    expected files so verify_outputs passes immediately."""
    td = Path(tempfile.mkdtemp(prefix="diag_l1l2_"))
    if populate_files:
        for rel in EXPECTED_PATHS:
            p = td / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                f"// stub for {rel} pre-populated by diag\nusing UnityEngine;\n"
                f"public class {Path(rel).stem} : MonoBehaviour {{}}\n",
                encoding="utf-8",
            )
    return td


async def run_one_trial(scenario: str, base_url: str, api_key: str,
                        project_root: Path) -> dict:
    """One CrewAI Agent kickoff with output_pydantic=ExecutorOutput + verify_outputs."""
    from crewai import Agent, Crew, Process, Task, LLM
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field
    from domain.crew_specs import ExecutorOutput
    from src.tools.builtin.local.verify_outputs import make_verify_outputs_tool

    # Bridge env api_key (CrewAI Converter / Instructor needs it).
    if api_key:
        os.environ["DASHSCOPE_API_KEY"] = api_key

    fired_tools: list[str] = []

    # Mock write_file that actually writes (so the missing-files scenario can self-correct).
    class WriteFileArgs(BaseModel):
        path: str = Field(description="Relative path under project root")
        content: str = Field(description="File content")

    class WriteFile(BaseTool):
        name: str = "write_file"
        description: str = "Write text content to a file path (creates parents)."
        args_schema: type[BaseModel] = WriteFileArgs
        def _run(self, path: str, content: str) -> str:
            fired_tools.append("write_file")
            abs_path = project_root / path if not Path(path).is_absolute() else Path(path)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            return f"OK — wrote {len(content)} bytes to {path}"

    class CreateScriptArgs(BaseModel):
        path: str = Field(description="Relative .cs path")
        skeleton: dict = Field(default_factory=dict, description="Class/namespace/methods spec")

    class CreateScript(BaseTool):
        name: str = "create_script"
        description: str = "Create a Unity C# script with the given skeleton."
        args_schema: type[BaseModel] = CreateScriptArgs
        def _run(self, path: str, skeleton: dict | None = None) -> str:
            fired_tools.append("create_script")
            abs_path = project_root / path if not Path(path).is_absolute() else Path(path)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            name = Path(path).stem
            body = (
                f"using UnityEngine;\npublic class {name} : MonoBehaviour {{}}\n"
            )
            abs_path.write_text(body, encoding="utf-8")
            return f"OK — created {path}"

    # The real Layer 2 tool, bound to our temp root + expected paths.
    vo_wrapper = make_verify_outputs_tool(
        project_root=str(project_root),
        expected_paths=EXPECTED_PATHS,
    )
    # crewai expects BaseTool — wrap our GuardedLocalTool which already
    # subclasses BaseTool via _base.
    class VerifyOutputsTracker(BaseTool):
        name: str = "verify_outputs"
        description: str = vo_wrapper.description
        args_schema: type[BaseModel] = vo_wrapper.args_schema
        def _run(self, file_paths: list[str]) -> str:
            fired_tools.append("verify_outputs")
            return vo_wrapper._run(file_paths)

    llm = LLM(
        model="dashscope/qwen-plus",
        api_key=api_key,
        base_url=base_url,
        is_litellm=True,
    )

    agent = Agent(
        role="Unity Developer",
        goal="实装两个 C# 脚本并最终输出 ExecutorOutput 结构化结果。",
        backstory=(
            "System Implementation Crew 的实装 Executor。流程：\n"
            "(1) 用 create_script 或 write_file 把每个 .cs 文件写到磁盘；\n"
            "(2) **必须**调一次 verify_outputs(file_paths=[...]) 自检；\n"
            "(3) 通过后再产出 ExecutorOutput JSON。\n"
            "如果 verify_outputs 报 missing，回到 (1) 补文件再 verify。"
        ),
        llm=llm,
        tools=[WriteFile(), CreateScript(), VerifyOutputsTracker()],
        max_iter=5,
        verbose=False,
        allow_delegation=False,
    )

    description = (
        "## 任务：实装两个脚本\n\n"
        f"项目根目录：`{project_root}`\n\n"
        "你必须产出以下两个文件，路径都是相对项目根的：\n"
        + "\n".join(f"  - {p}" for p in EXPECTED_PATHS)
        + "\n\n两个脚本都是 MonoBehaviour 子类，简单骨架即可。"
        + "\n\n**严格流程**：先写文件 → verify_outputs 通过 → 输出 ExecutorOutput。"
        + "\n\n输出形态：file_paths 列出实际写入的两个路径，"
        + "coverage 用 {filename: 1} 之类即可，summary 一句话。"
    )

    task = Task(
        description=description,
        expected_output="ExecutorOutput JSON",
        agent=agent,
        output_pydantic=ExecutorOutput,
    )
    crew = Crew(
        agents=[agent], tasks=[task],
        process=Process.sequential, verbose=False,
    )

    err = None
    pydantic_obj = None
    try:
        result = crew.kickoff()
        task_output = task.output
        if task_output is not None:
            pydantic_obj = getattr(task_output, "pydantic", None)
    except Exception as exc:
        err = f"{type(exc).__name__}: {str(exc)[:300]}"

    # Disk truth check
    on_disk = [
        p for p in EXPECTED_PATHS
        if (project_root / p).exists()
        and (project_root / p).stat().st_size > 0
    ]

    # Simulate workflow_svc's server-side disk truth check (Layer 2
    # belt-and-suspenders): even if agent claims success in Spec, if
    # the claimed file_paths don't all exist on disk, the step fails.
    server_side_ok = True
    server_side_reason = ""
    if pydantic_obj is not None:
        claimed = pydantic_obj.model_dump().get("file_paths", []) or []
        missing = []
        for rel in claimed:
            ap = (project_root / rel) if not Path(rel).is_absolute() else Path(rel)
            if not ap.exists() or (ap.is_file() and ap.stat().st_size == 0):
                missing.append(rel)
        if missing:
            server_side_ok = False
            server_side_reason = f"missing/empty: {missing}"

    return {
        "scenario": scenario,
        "error": err,
        "pydantic_ok": pydantic_obj is not None,
        "pydantic_dump": pydantic_obj.model_dump() if pydantic_obj else None,
        "fired_tools": fired_tools,
        "verify_outputs_called": "verify_outputs" in fired_tools,
        "files_on_disk": on_disk,
        "n_expected_on_disk": len(on_disk),
        "server_side_ok": server_side_ok,
        "server_side_reason": server_side_reason,
    }


async def main():
    base_url, api_key = load_provider("Qwen")
    print(f"Layer 1+2 integration test (Qwen) — {TRIALS_PER_SCENARIO} trials/scenario\n")

    all_results = {}
    for scenario, populate in [
        ("A_files_already_exist", True),
        ("B_files_missing", False),
    ]:
        print(f"{'=' * 70}\n  Scenario {scenario}  (populate_files={populate})\n{'=' * 70}")
        trials = []
        for i in range(TRIALS_PER_SCENARIO):
            td = setup_temp_project(populate_files=populate)
            r = await run_one_trial(scenario, base_url, api_key, td)
            trials.append(r)
            print(f"  Trial {i+1}: "
                  f"pyd={'✓' if r['pydantic_ok'] else '✗'}  "
                  f"verify_called={'✓' if r['verify_outputs_called'] else '✗'}  "
                  f"on_disk={r['n_expected_on_disk']}/{len(EXPECTED_PATHS)}  "
                  f"server_side={'✓ pass' if r['server_side_ok'] else '✗ FAIL'}  "
                  f"tools={r['fired_tools']}")
            if not r["server_side_ok"]:
                print(f"    server-side reason: {r['server_side_reason']}")
            if r["error"]:
                print(f"    err: {r['error']}")
        all_results[scenario] = trials

    print(f"\n{'#' * 70}\n  TALLY\n{'#' * 70}")
    for scenario, trials in all_results.items():
        n = len(trials)
        py_ok = sum(1 for t in trials if t["pydantic_ok"])
        vo_called = sum(1 for t in trials if t["verify_outputs_called"])
        full_on_disk = sum(1 for t in trials if t["n_expected_on_disk"] == len(EXPECTED_PATHS))
        errs = sum(1 for t in trials if t["error"])
        ss_ok = sum(1 for t in trials if t["server_side_ok"])
        print(f"\n  {scenario}:")
        print(f"    pydantic_ok       : {py_ok}/{n}")
        print(f"    verify_outputs    : {vo_called}/{n}")
        print(f"    all files on disk : {full_on_disk}/{n}")
        print(f"    server-side OK    : {ss_ok}/{n}  (Layer 2 enforcement)")
        print(f"    errors            : {errs}/{n}")
        # Interpret outcome:
        if scenario == "A_files_already_exist":
            print(f"    expected: server-side OK = {n}/{n} (pre-existing files)")
        elif scenario == "B_files_missing":
            print(f"    expected: server-side FAIL = {n}/{n} (Layer 2 catches cheat)"
                  " OR agent writes files (Layer 2 self-correct loop)")

    out = ROOT / "data" / "diag_layer1_layer2_results.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2,
                              default=str), encoding="utf-8")
    print(f"\n  Full results: {out}")


if __name__ == "__main__":
    asyncio.run(main())
