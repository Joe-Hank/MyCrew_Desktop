"""Reproduce the executor's 'raw_text instead of tool_calls' failure
*inside* CrewAI 1.14 with deepseek-v4-flash, monkey-patching litellm
to capture the exact request/response it sees.

Phase 1 feedback loop for fruit-ninja Bug B: we already proved
(diag_forced_tool_choice) that deepseek emits tool_calls fine via raw
LiteLLM. The remaining unknown is how CrewAI 1.14's Agent loop
constructs the request — specifically: tool_choice value, system
prompt content (ReAct vs native), tool schema shape.

Run from backend/ with venv python:
    backend/.venv/Scripts/python.exe scripts/diag_crewai_executor_repro.py
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_provider() -> tuple[str, str]:
    db = sqlite3.connect(
        str(Path(__file__).parent.parent.parent / "data" / "db" / "mycrew.db")
    )
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute(
        "SELECT base_url, api_key_ref FROM llm_providers WHERE type='deepseek'"
    )
    r = cur.fetchone()
    db.close()
    if not r:
        raise SystemExit("No deepseek provider in DB.")
    return r["base_url"], r["api_key_ref"]


CAPTURED: list[dict] = []


def install_litellm_capture() -> None:
    """Wrap BOTH litellm.completion (sync) and litellm.acompletion so every
    call is logged before/after — CrewAI 1.14 uses both paths."""
    import litellm

    orig_async = litellm.acompletion
    orig_sync = litellm.completion

    def _log_request(kwargs):
        idx = len(CAPTURED)
        entry = {
            "idx": idx,
            "request": {
                "model": kwargs.get("model"),
                "tool_choice": kwargs.get("tool_choice"),
                "tools_count": len(kwargs.get("tools") or []),
                "tools_summary": [
                    (t.get("function", {}).get("name"),
                     len(json.dumps(t.get("function", {}).get("parameters") or {})))
                    for t in (kwargs.get("tools") or [])
                ],
                "messages": kwargs.get("messages"),
                "stream": kwargs.get("stream"),
            },
        }
        CAPTURED.append(entry)
        print(f"\n>>> LiteLLM call #{idx}")
        print(f"    model        : {entry['request']['model']}")
        print(f"    tool_choice  : {entry['request']['tool_choice']!r}")
        print(f"    tools        : {entry['request']['tools_count']}")
        for name, schemalen in entry["request"]["tools_summary"][:6]:
            print(f"        - {name}  (schema_len={schemalen})")
        if entry["request"]["tools_count"] > 6:
            print(f"        ... and {entry['request']['tools_count']-6} more")
        msgs = entry["request"]["messages"] or []
        print(f"    messages     : {len(msgs)} entries")
        for i, m in enumerate(msgs):
            role = m.get("role")
            content = str(m.get("content") or "")
            print(f"      [{i}] role={role}  content[0:300]={content[:300]!r}")
        return entry

    def _log_response(entry, resp, exc=None):
        if exc is not None:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            print(f"<<< EXCEPTION: {entry['error']}")
            return
        try:
            raw = resp.model_dump() if hasattr(resp, "model_dump") else resp.__dict__
        except Exception:
            raw = {"_repr": repr(resp)}
        entry["response"] = raw
        choice0 = (raw.get("choices") or [{}])[0]
        msg = choice0.get("message", {}) or {}
        tcs = msg.get("tool_calls") or []
        print(f"<<< response finish_reason={choice0.get('finish_reason')}")
        content = msg.get("content") or ""
        print(f"    content (len={len(content)}, first 400) : {content[:400]!r}")
        print(f"    tool_calls count    : {len(tcs)}")
        for j, tc in enumerate(tcs):
            fn = tc.get("function", {})
            print(f"      [{j}] name={fn.get('name')}  args[0:200]={(fn.get('arguments') or '')[:200]!r}")
        rc = msg.get("reasoning_content")
        if rc:
            print(f"    reasoning_content[0:200] : {rc[:200]!r}")

    async def traced_async(**kwargs):
        entry = _log_request(kwargs)
        try:
            resp = await orig_async(**kwargs)
        except Exception as exc:
            _log_response(entry, None, exc)
            raise
        _log_response(entry, resp)
        return resp

    def traced_sync(**kwargs):
        entry = _log_request(kwargs)
        try:
            resp = orig_sync(**kwargs)
        except Exception as exc:
            _log_response(entry, None, exc)
            raise
        _log_response(entry, resp)
        return resp

    litellm.acompletion = traced_async
    litellm.completion = traced_sync


async def main() -> None:
    install_litellm_capture()
    base_url, api_key = load_provider()
    print(f"Provider: base_url={base_url}  api_key={api_key[:10]}...")

    from crewai import Agent, Crew, Process, Task, LLM
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field

    import os
    is_litellm_flag = os.environ.get("DIAG_IS_LITELLM", "true").lower() == "true"
    llm = LLM(
        model="deepseek/deepseek-v4-flash",
        api_key=api_key,
        base_url=base_url,
        is_litellm=is_litellm_flag,
    )
    print(f"LLM class: {type(llm).__name__}  is_litellm={getattr(llm, 'is_litellm', '?')}  passed_flag={is_litellm_flag}")

    # ── Minimal tool that mirrors emit_output's shape ──────────────
    class EmitInput(BaseModel):
        payload: dict = Field(description="Output payload dict")

    class EmitOutputMock(BaseTool):
        name: str = "emit_output"
        description: str = "Submit your final structured output."
        args_schema: type[BaseModel] = EmitInput

        def _run(self, payload: dict) -> str:
            return json.dumps({"ok": True, "captured": payload}, ensure_ascii=False)

    emit_tool = EmitOutputMock()

    # ── Mock 40 Unity MCP-shaped tools to match real Unity Developer ────
    class UnityNoopInput(BaseModel):
        action: str = Field(description="Unity action name")
        params: dict = Field(default_factory=dict, description="Params dict")

    class UnityNoopTool(BaseTool):
        name: str = "noop"
        description: str = "Unity MCP tool"
        args_schema: type[BaseModel] = UnityNoopInput
        def _run(self, action: str, params: dict | None = None) -> str:
            return json.dumps({"ok": True, "tool": self.name, "action": action})

    def _make_unity_tool(tool_name: str, desc: str):
        return UnityNoopTool(name=tool_name, description=desc)

    unity_tool_names = [
        "create_script", "script_apply_edits", "apply_text_edits", "find_in_file",
        "validate_script", "refresh_unity", "manage_gameobject", "manage_components",
        "set_property", "manage_asset", "read_file_local", "list_directory_local",
        "git_status", "git_diff", "git_add", "git_commit",
        "search_assets", "create_prefab", "modify_prefab", "delete_asset",
        "create_directory", "copy_file", "move_file", "rename_file",
        "get_console_logs", "clear_console", "play_mode_enter", "play_mode_exit",
        "scene_save", "scene_load", "scene_new", "build_project",
        "list_packages", "install_package", "update_package", "import_package",
        "shader_compile", "material_create", "mesh_combine", "lightmap_bake",
    ]
    unity_tools = [_make_unity_tool(n, f"Unity MCP tool: {n}") for n in unity_tool_names]
    all_tools = [emit_tool] + unity_tools
    print(f"\nTotal tools attached to agent: {len(all_tools)}")

    # Mimic the executor: real Unity Developer role + executor instructions
    # but trimmed so we don't burn 5min/test.
    agent = Agent(
        role="Unity Developer",
        goal="按规格用 Unity MCP 工具创建 C# 脚本并产出 emit_output 报告。",
        backstory=(
            "你是一名熟练的 Unity 开发者。完成任务后必须调 emit_output 工具"
            "提交结构化结果——只输出文本算未完成。"
        ),
        llm=llm,
        tools=all_tools,
        max_iter=2,
        verbose=True,
        allow_delegation=False,
    )

    description = (
        "## 任务: 实现 MouseSlicer.cs（mock，无需真创建文件）\n\n"
        "你只需调一次 emit_output 工具提交以下 payload：\n"
        "  {'file_paths': ['Assets/Scripts/Slicing/MouseSlicer.cs'], 'coverage': {'MouseSlicer.cs': 5}}\n"
        "不要在思考里写 'Action: emit_output'，必须真调用工具。"
    )

    task = Task(
        description=description,
        expected_output="调一次 emit_output 后返回工具结果。",
        agent=agent,
    )

    crew = Crew(
        agents=[agent], tasks=[task],
        process=Process.sequential, verbose=False,
    )

    print("\n==== kickoff() (sync) ====")
    # Use sync kickoff() because that's what crewai_runner.py runs in
    # workflow_svc (via asyncio.to_thread). Sync path goes through
    # litellm.completion, not acompletion.
    result = crew.kickoff()
    print("\n==== final result ====")
    print(f"raw     : {str(result)[:400]!r}")

    print(f"\n==== Summary: {len(CAPTURED)} LiteLLM call(s) captured ====")
    for c in CAPTURED:
        req = c["request"]
        resp = c.get("response", {})
        ch0 = (resp.get("choices") or [{}])[0]
        tcs = (ch0.get("message", {}) or {}).get("tool_calls") or []
        content = (ch0.get("message", {}) or {}).get("content") or ""
        print(f"  call#{c['idx']}: tool_choice={req['tool_choice']!r}  "
              f"tools={req['tools_count']}  "
              f"finish={ch0.get('finish_reason')}  "
              f"tool_calls={len(tcs)}  content_len={len(content)}")


if __name__ == "__main__":
    # main() does sync kickoff inside; we still need an event loop only
    # for the await-able provider-load and litellm init.
    asyncio.run(main())
