"""CrewAI bridge — run a single task via a real CrewAI Agent/Crew/Task pipeline.

Plan: workflow_svc._run_agent delegates here when the agent's tools/MCPs need
the CrewAI execution loop (vs. simple LLM completion).

This module isolates all crewai imports so the rest of the codebase doesn't
take a hard dependency on CrewAI being importable.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from infra.repo import crud
from services.permission_guard import PermissionDenied

log = structlog.get_logger()


# ── LLM construction ──────────────────────────────────────────────

def _build_litellm_model_string(provider_type: str, model_name: str) -> str:
    """Return the model string expected by CrewAI / litellm.

    litellm naming conventions:
      - OpenAI direct           → "openai/gpt-4o"
      - Anthropic               → "anthropic/claude-3-5-sonnet-20241022"
      - Gemini                  → "gemini/gemini-1.5-pro"
      - Ollama                  → "ollama/llama3"
      - OpenAI-compatible custom (Qwen/Deepseek/GLM/MiMo via dashscope etc.):
            use "openai/MODEL" and pass api_base
    """
    t = (provider_type or "openai").lower()
    if t in ("openai", "qwen", "deepseek", "custom"):
        return f"openai/{model_name}"
    if t == "anthropic":
        return f"anthropic/{model_name}"
    if t == "gemini":
        return f"gemini/{model_name}"
    if t == "ollama":
        return f"ollama/{model_name}"
    return model_name  # let litellm guess


def _build_crewai_llm(provider: dict, model_name: str):
    """Build a `crewai.LLM` instance from a v3 provider row."""
    from crewai import LLM

    model_string = _build_litellm_model_string(provider.get("type", "openai"), model_name)
    kwargs: dict[str, Any] = {
        "model": model_string,
        "api_key": provider.get("api_key_ref") or None,
    }
    base_url = provider.get("base_url")
    if base_url:
        kwargs["base_url"] = base_url
    return LLM(**kwargs)


# ── Tool resolution ───────────────────────────────────────────────

def _load_builtin_tools(tool_names: list[str]) -> list:
    """Resolve tool names → CrewAI BaseTool instances from our builtin registry.

    Currently maps:
      - read_file, list_directory   → mcp_filesystem.*
      - execute_blender_code, get_scene_info → mcp_blender.*

    Unknown names are silently skipped (agent runs with whatever subset
    of tools is resolvable). Log a warning for each skipped name.
    """
    instances: list = []
    name_set = {n for n in tool_names}

    try:
        from src.tools.builtin.mcp_filesystem.read_file import ReadFile
        from src.tools.builtin.mcp_filesystem.list_directory import ListDirectory
        from src.tools.builtin.mcp_blender.execute_code import ExecuteBlenderCode
        from src.tools.builtin.mcp_blender.get_scene_info import GetSceneInfo
    except Exception as exc:
        log.warning("crewai_runner.tool_import_failed", error=str(exc))
        return instances

    registry = {
        "read_file": ReadFile,
        "list_directory": ListDirectory,
        "execute_blender_code": ExecuteBlenderCode,
        "get_scene_info": GetSceneInfo,
        # NB: "create_workflow" is intentionally NOT registered here. It must
        # be instantiated via make_create_workflow_tool(session_id) in
        # inception_svc — instantiating it without a bound session_id is a
        # bug. If a non-Plan-Maker agent has create_workflow in its tool_ids
        # it will be silently skipped (with a log).
    }

    # Tools that should be ignored when discovered in a generic agent's tool_ids
    # (they need special instantiation done elsewhere).
    SPECIAL_TOOLS = {"create_workflow"}

    for n in tool_names:
        if n in SPECIAL_TOOLS:
            log.info("crewai_runner.tool_skipped", tool=n, reason="special_instantiation")
            continue
        cls = registry.get(n)
        if cls is None:
            log.info("crewai_runner.tool_skipped", tool=n, reason="no_builtin")
            continue
        try:
            instances.append(cls())
        except Exception as exc:
            log.warning("crewai_runner.tool_init_failed", tool=n, error=str(exc))

    # Unknown tools that user has in DB but no implementation: warn once
    unknown = name_set - set(registry.keys())
    if unknown:
        log.info("crewai_runner.unknown_tools", names=list(unknown))

    return instances


async def _resolve_agent_tools(agent_row: dict) -> list:
    """Look up tool rows referenced by an agent → return BaseTool instances."""
    tool_ids = agent_row.get("tool_ids", [])
    if isinstance(tool_ids, str):
        try:
            tool_ids = json.loads(tool_ids)
        except (json.JSONDecodeError, TypeError):
            tool_ids = []

    if not tool_ids:
        return []

    names: list[str] = []
    for tid in tool_ids:
        row = await crud.get_by_id("tools", tid)
        if row and row.get("name"):
            names.append(row["name"])
    return _load_builtin_tools(names)


# ── Main entrypoint ───────────────────────────────────────────────

async def run_task_with_crewai(
    agent_row: dict,
    task_input: Any,
    provider_id: str,
    model_name: str,
) -> str:
    """Run a single task using real CrewAI Agent/Crew/Task.

    Returns the agent's text output. Permission denials are caught and
    surfaced as readable text rather than exceptions, so downstream
    validation can decide how to react.

    Raises any non-permission exception from CrewAI / the LLM.
    """
    from crewai import Agent, Crew, Process, Task

    provider = await crud.get_by_id("llm_providers", provider_id)
    if not provider:
        raise ValueError(f"LLM provider {provider_id} not found")

    llm = _build_crewai_llm(provider, model_name)
    tools = await _resolve_agent_tools(agent_row)

    role = agent_row.get("role") or "Assistant"
    goal = agent_row.get("goal") or "完成分配的任务"
    backstory = agent_row.get("backstory") or "你是一个专业的 AI 助手。"

    agent = Agent(
        role=role,
        goal=goal,
        backstory=backstory,
        llm=llm,
        tools=tools or None,
        max_iter=int(agent_row.get("max_retry") or 3),
        verbose=False,
        allow_delegation=False,
    )

    # Compose task description with upstream context + output schema hint
    desc_parts: list[str] = [f"## 任务: {task_input.title}", "", task_input.detail or ""]
    if task_input.upstream_outputs:
        desc_parts.append("\n## 上游任务输出（供参考）:")
        for uid, out in task_input.upstream_outputs.items():
            desc_parts.append(f"\n### 来自任务 {uid}:")
            desc_parts.append("```json")
            desc_parts.append(json.dumps(out, ensure_ascii=False, indent=2))
            desc_parts.append("```")
    if task_input.output_schema and task_input.output_schema != {}:
        desc_parts.append("\n## 输出要求 (JSON Schema):")
        desc_parts.append("```json")
        desc_parts.append(json.dumps(task_input.output_schema, ensure_ascii=False, indent=2))
        desc_parts.append("```")

    description = "\n".join(desc_parts)
    expected_output = (
        "若有输出 schema 请按 schema 输出 JSON，否则用自然语言总结结果。"
    )

    task = Task(
        description=description,
        expected_output=expected_output,
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
        memory=False,  # v3 hasn't wired memory yet; experience_repo is TODO
    )

    log.info("crewai_runner.start", task_id=task_input.task_id, agent_role=role,
             tool_count=len(tools), model=model_name)

    try:
        # CrewAI's kickoff() is sync; run in threadpool to avoid blocking event loop
        result = await asyncio.to_thread(crew.kickoff)
    except PermissionDenied as exc:
        log.warning("crewai_runner.permission_denied",
                    task_id=task_input.task_id, kind=exc.kind)
        return f"[PermissionDenied] {exc}"
    except Exception as exc:
        log.error("crewai_runner.kickoff_failed",
                  task_id=task_input.task_id, error=str(exc))
        raise

    # Result is a CrewOutput; convert to string
    output_text = str(result.raw if hasattr(result, "raw") else result)
    log.info("crewai_runner.finished", task_id=task_input.task_id,
             output_len=len(output_text))
    return output_text
