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
    """Return the model string expected by CrewAI.

    CrewAI ≥1.14 ships a *native* provider set and treats `openai/<model>` as
    a real OpenAI request — feeding it an arbitrary non-OpenAI model name
    fails initialisation. We therefore pick a CrewAI-native prefix matching
    the provider type, so litellm is not required:

      - deepseek  → "deepseek/<model>"     (native; uses api.deepseek.com)
      - qwen      → "dashscope/<model>"    (native; uses DashScope endpoint)
      - custom    → "hosted_vllm/<model>"  (native OpenAI-compat; needs base_url)
      - openai    → "openai/<model>"
      - anthropic → "anthropic/<model>"
      - gemini    → "gemini/<model>"
      - ollama    → "ollama/<model>"
    """
    t = (provider_type or "openai").lower()
    if t == "openai":
        return f"openai/{model_name}"
    if t == "anthropic":
        return f"anthropic/{model_name}"
    if t == "gemini":
        return f"gemini/{model_name}"
    if t == "ollama":
        return f"ollama/{model_name}"
    if t == "deepseek":
        return f"deepseek/{model_name}"
    if t == "qwen":
        return f"dashscope/{model_name}"
    if t == "custom":
        return f"hosted_vllm/{model_name}"
    return model_name


def _build_crewai_llm(
    provider: dict,
    model_name: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
):
    """Build a `crewai.LLM` instance from a v3 provider row.

    Optional `temperature` + `max_tokens` are passed through to litellm
    when set — used by Plan Maker 2.0 sub-agents to tune per-intent
    output behavior (cheap classifier at temp=0 vs creative architect
    at temp=0.7, etc.).
    """
    from crewai import LLM

    model_string = _build_litellm_model_string(provider.get("type", "openai"), model_name)
    kwargs: dict[str, Any] = {
        "model": model_string,
        "api_key": provider.get("api_key_ref") or None,
    }
    base_url = provider.get("base_url")
    if base_url:
        kwargs["base_url"] = base_url
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    if max_tokens is not None:
        kwargs["max_tokens"] = int(max_tokens)
    return LLM(**kwargs)


# ── Tool resolution ───────────────────────────────────────────────

def _load_builtin_tools(tool_names: list[str], ctx: dict | None = None) -> list:
    """Resolve tool names → CrewAI BaseTool instances from our builtin registry.

    `ctx` is the per-task execution context with keys:
      - project_id, project_root (workspace-scoped local tools need it)
      - task_id, output_schema   (emit_output binds these)

    Unknown names are silently skipped (agent runs with whatever subset
    of tools is resolvable). Log a warning for each skipped name.
    """
    instances: list = []
    name_set = {n for n in tool_names}
    ctx = ctx or {}

    try:
        # MCP-backed
        from src.tools.builtin.mcp_filesystem.read_file import ReadFile
        from src.tools.builtin.mcp_filesystem.list_directory import ListDirectory
        from src.tools.builtin.mcp_blender.execute_code import ExecuteBlenderCode
        from src.tools.builtin.mcp_blender.get_scene_info import GetSceneInfo
        from src.tools.builtin.mcp_blender.more_tools import (
            GetObjectInfo, GetViewportScreenshot,
            SearchPolyhavenAssets, DownloadPolyhavenAsset, SetTexture,
            GenerateHyper3DModelViaText, PollRodinJobStatus,
            ImportGeneratedAsset,
        )
        from src.tools.builtin.mcp_comfyui.tools import (
            ComfyCreateWorkflowFromTemplate, ComfyValidateWorkflow,
            ComfyEnqueueWorkflow, ComfyGetJobStatus, ComfyGetHistory,
            ComfyListLocalModels, ComfyListOutputImages, ComfyUploadImage,
        )
        from src.tools.builtin.mcp_figma.tools import (
            FigmaGetDesignContext, FigmaGetScreenshot, FigmaGetMetadata,
            FigmaGetVariableDefs, FigmaGenerateDiagram,
        )
        from src.tools.builtin.mcp_tavily.tools import (
            TavilySearch, TavilyExtract, TavilyResearch,
        )
        # Local + factory-bound
        from src.tools.builtin.local.workspace import make_workspace_tools
        from src.tools.builtin.local.emit_output import make_emit_output_tool
        from src.tools.builtin.local.synth_8bit_sfx import make_synth_8bit_sfx_tool
        from src.tools.builtin.mcp_git.tools import make_git_tools
        # Unity MCP — pre-instantiated CrewStructuredTool instances
        from src.tools.builtin.unity import TOOL_MAP as UNITY_TOOL_MAP
    except Exception as exc:
        log.warning("crewai_runner.tool_import_failed", error=str(exc))
        return instances

    # MCP / context-free tool classes — instantiate per-call
    static_registry = {
        # filesystem
        "read_file": ReadFile,
        "list_directory": ListDirectory,
        # blender
        "execute_blender_code": ExecuteBlenderCode,
        "get_scene_info": GetSceneInfo,
        "get_object_info": GetObjectInfo,
        "get_viewport_screenshot": GetViewportScreenshot,
        "search_polyhaven_assets": SearchPolyhavenAssets,
        "download_polyhaven_asset": DownloadPolyhavenAsset,
        "set_texture": SetTexture,
        "generate_hyper3d_model_via_text": GenerateHyper3DModelViaText,
        "poll_rodin_job_status": PollRodinJobStatus,
        "import_generated_asset": ImportGeneratedAsset,
        # comfyui
        "comfy_create_workflow_from_template": ComfyCreateWorkflowFromTemplate,
        "comfy_validate_workflow": ComfyValidateWorkflow,
        "comfy_enqueue_workflow": ComfyEnqueueWorkflow,
        "comfy_get_job_status": ComfyGetJobStatus,
        "comfy_get_history": ComfyGetHistory,
        "comfy_list_local_models": ComfyListLocalModels,
        "comfy_list_output_images": ComfyListOutputImages,
        "comfy_upload_image": ComfyUploadImage,
        # figma
        "figma_get_design_context": FigmaGetDesignContext,
        "figma_get_screenshot": FigmaGetScreenshot,
        "figma_get_metadata": FigmaGetMetadata,
        "figma_get_variable_defs": FigmaGetVariableDefs,
        "figma_generate_diagram": FigmaGenerateDiagram,
        # tavily
        "tavily_search": TavilySearch,
        "tavily_extract": TavilyExtract,
        "tavily_research": TavilyResearch,
    }

    # Context-bound tools: built lazily so we only resolve project root /
    # task schema when the agent actually requests them.
    workspace_cache: dict | None = None
    git_cache: dict | None = None

    def _get_workspace() -> dict:
        nonlocal workspace_cache
        if workspace_cache is None:
            workspace_cache = make_workspace_tools(ctx.get("project_root"))
        return workspace_cache

    def _get_git() -> dict:
        nonlocal git_cache
        if git_cache is None:
            git_cache = make_git_tools(ctx.get("project_root"))
        return git_cache

    bound_registry = {
        # workspace
        "write_file": lambda: _get_workspace()["write_file"],
        "mkdir": lambda: _get_workspace()["mkdir"],
        "read_file_local": lambda: _get_workspace()["read_file_local"],
        "list_directory_local": lambda: _get_workspace()["list_directory_local"],
        # output capture
        "emit_output": lambda: make_emit_output_tool(
            ctx.get("task_id") or "",
            ctx.get("output_schema") or {},
            ctx.get("project_root"),
            ctx.get("output_paths") or None,
        ),
        # 8-bit audio synthesis (Audio Crew executor)
        "synth_8bit_sfx": lambda: make_synth_8bit_sfx_tool(ctx.get("project_root")),
        # git
        "git_status": lambda: _get_git()["git_status"],
        "git_log": lambda: _get_git()["git_log"],
        "git_diff_unstaged": lambda: _get_git()["git_diff_unstaged"],
        "git_diff_staged": lambda: _get_git()["git_diff_staged"],
        "git_add": lambda: _get_git()["git_add"],
        "git_commit": lambda: _get_git()["git_commit"],
    }

    # NB: "create_workflow" / "assign_agents" are intentionally NOT
    # registered here — they are Plan-Maker-only and require session
    # binding done in inception_svc.
    SPECIAL_TOOLS = {"create_workflow", "assign_agents"}

    for n in tool_names:
        if n in SPECIAL_TOOLS:
            log.info("crewai_runner.tool_skipped", tool=n, reason="special_instantiation")
            continue
        try:
            if n in static_registry:
                instances.append(static_registry[n]())
            elif n in bound_registry:
                instances.append(bound_registry[n]())
            elif n in UNITY_TOOL_MAP:
                # Unity MCP tools are pre-instantiated singletons (stateless
                # bridge wrappers — safe to share across agents).
                instances.append(UNITY_TOOL_MAP[n])
            else:
                log.info("crewai_runner.tool_skipped", tool=n, reason="no_builtin")
        except Exception as exc:
            log.warning("crewai_runner.tool_init_failed", tool=n, error=str(exc))

    # Unknown tools that user has in DB but no implementation: warn once
    known = (set(static_registry.keys()) | set(bound_registry.keys())
             | set(UNITY_TOOL_MAP.keys()) | SPECIAL_TOOLS)
    unknown = name_set - known
    if unknown:
        log.info("crewai_runner.unknown_tools", names=list(unknown))

    return instances


async def _resolve_agent_tools(agent_row: dict, ctx: dict | None = None) -> list:
    """Look up tool rows referenced by an agent → return BaseTool instances.

    `ctx` is the per-task execution context (project_id, project_root,
    task_id, output_schema). Forwarded to `_load_builtin_tools` so
    workspace + emit_output tools can bind correctly.
    """
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
    return _load_builtin_tools(names, ctx)


# ── Main entrypoint ───────────────────────────────────────────────

def _extract_step_text(step: object) -> str:
    """Best-effort extraction of human-readable text from a CrewAI step
    callback. Mirrors the inception_svc helper — CrewAI step shapes vary
    across versions so we probe common attributes and stringify defensively."""
    try:
        output = getattr(step, "output", None)
        if isinstance(output, str) and output.strip():
            return output.strip()[:600]
        rv = getattr(step, "return_values", None)
        if isinstance(rv, dict) and rv.get("output"):
            return str(rv["output"])[:600]
        tool = getattr(step, "tool", None)
        tool_input = getattr(step, "tool_input", None)
        if tool:
            summary = f"⚙️ {tool}"
            if tool_input:
                summary += f"({str(tool_input)[:120]}...)"
            return summary
        s = str(step)[:400]
        return s if s and s != "None" else ""
    except Exception:
        return ""


async def run_task_with_crewai(
    agent_row: dict,
    task_input: Any,
    provider_id: str,
    model_name: str,
    project_id: str | None = None,
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

    # Per-task execution context for tool binding (workspace tools need
    # project_root; emit_output needs task_id + output_schema).
    project_root: str | None = None
    if project_id:
        project_row = await crud.get_by_id("projects", project_id)
        if project_row:
            project_root = project_row.get("root_path") or None
    tool_ctx = {
        "project_id": project_id,
        "project_root": project_root,
        "task_id": task_input.task_id,
        "output_schema": task_input.output_schema or {},
        # Stage E: forward the PM's must-produce file list (may be None)
        # so emit_output can verify each entry exists regardless of
        # which schema field the agent puts them in.
        "output_paths": task_input.output_paths,
    }
    tools = await _resolve_agent_tools(agent_row, tool_ctx)

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

    # ── Step callback → WS broadcast for the "Agent 输出" log tab ──
    # Fires once per CrewAI step (LLM call OR tool call completes). The
    # callback runs on a worker thread (CrewAI's kickoff is sync); we
    # hop back to the main event loop to call manager.broadcast safely.
    main_loop = asyncio.get_running_loop()
    step_n = {"n": 0}

    def _step_cb(step: object) -> None:
        step_n["n"] += 1
        # Every step proves the task is still alive — keep watchdog happy
        # even on steps that yield no broadcastable text.
        try:
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()
            asyncio.run_coroutine_threadsafe(
                crud.update_by_id("tasks", task_input.task_id,
                                  {"last_activity_at": now_iso}),
                main_loop,
            )
        except Exception as exc:
            log.warning("crewai_runner.heartbeat_failed", error=str(exc))

        text = _extract_step_text(step)
        if not text:
            return
        try:
            from api.ws import manager
            asyncio.run_coroutine_threadsafe(
                manager.broadcast("agent.output", {
                    "project_id": project_id,
                    "task_id": task_input.task_id,
                    "agent_role": role,
                    "step": step_n["n"],
                    "text": text,
                }),
                main_loop,
            )
        except Exception as exc:
            log.warning("crewai_runner.step_broadcast_failed", error=str(exc))

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
        memory=False,  # v3 hasn't wired memory yet; experience_repo is TODO
        step_callback=_step_cb,
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


# ── PM v4 Crew step runner ────────────────────────────────────────
#
# One CrewAI Agent + one CrewAI Task = one step of a Crew. The Crew
# orchestrator in workflow_svc walks the head→executors→QA sequence
# itself (manual for-loop), so each step is a fresh single-step Crew
# kickoff. That keeps step boundaries clean for: pause checks, per-step
# emit_output capture, sub-step IO files, and progress WS events.

async def run_crew_step_with_crewai(
    *,
    agent_row: dict,
    step_role: str,                 # 'head' | 'executor' | 'qa'
    step_index: int,                # 0-based
    step_instructions: str,
    project_id: str,
    project_root: str | None,
    parent_task_id: str,            # the original Crew task id
    parent_task_title: str,
    parent_task_detail: str,
    parent_output_schema: dict,
    parent_output_paths: list[str],
    upstream_outputs: dict,
    prev_step_payload: dict | None,
    provider_id: str,
    model_name: str,
) -> tuple[str, dict | None]:
    """Run a single Crew step. Returns (raw_text, captured_emit_payload_or_None).

    The emit_output tool is bound to a step-namespaced task_id —
    `{parent_task_id}#step{i}` — so each step's payload lands in its
    own slot in `_output_capture._outputs`. The QA step (the chain's
    last) ALSO captures into the plain parent_task_id key so the
    existing workflow_svc post-processing picks it up unchanged.
    """
    from crewai import Agent, Crew, Process, Task

    provider = await crud.get_by_id("llm_providers", provider_id)
    if not provider:
        raise ValueError(f"LLM provider {provider_id} not found")

    llm = _build_crewai_llm(provider, model_name)

    # The QA step (chain's tail) writes into the parent task_id slot —
    # workflow_svc reads pop_output(task_id) after _run_crew returns.
    # All other steps write into a per-step namespace.
    step_task_key = (
        parent_task_id
        if step_role == "qa"
        else f"{parent_task_id}#step{step_index}"
    )

    # For QA we honour the full task.output_schema (PM contract). For
    # head/executors the schema is loose (Q4: dict accepted) — pass {}.
    bound_schema = parent_output_schema if step_role == "qa" else {}
    # Stage E: the QA step is the only one bound to the parent task_id
    # (its emit_output is what workflow_svc reads downstream), so it's
    # the right place to enforce the parent's output_paths contract.
    # Intermediate steps emit into per-step namespaces and aren't held
    # to the parent's file list.
    bound_expected_paths = (
        parent_output_paths if step_role == "qa" else None
    )

    tool_ctx = {
        "project_id": project_id,
        "project_root": project_root,
        "task_id": step_task_key,
        "output_schema": bound_schema,
        "output_paths": bound_expected_paths,
    }
    tools = await _resolve_agent_tools(agent_row, tool_ctx)

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

    # Description = step_instructions + PM contract block + prev-step
    # JSON payload (so the LLM has structured input, not just prose).
    desc_parts: list[str] = [
        f"## Crew 步骤 {step_index + 1}（角色：{step_role}）",
        "",
        step_instructions,
        "",
        f"## 父任务（PM 契约，**不允许修改**）",
        f"- 标题：{parent_task_title}",
        f"- 细节：{parent_task_detail or '(无)'}",
        f"- output_paths（必产）：{json.dumps(parent_output_paths or [], ensure_ascii=False)}",
        f"- output_schema：```json\n{json.dumps(parent_output_schema or {}, ensure_ascii=False, indent=2)}\n```",
    ]
    if upstream_outputs:
        desc_parts += [
            "",
            "## 上游任务输出（其他 task 的产物，可选参考）",
            "```json",
            json.dumps(upstream_outputs, ensure_ascii=False, indent=2),
            "```",
        ]
    if prev_step_payload is not None:
        desc_parts += [
            "",
            f"## 上一步（step {step_index}）的结构化输出",
            "```json",
            json.dumps(prev_step_payload, ensure_ascii=False, indent=2),
            "```",
            "下游 step 必须在这一份基础上推进；不要重新评估或忽略它。",
        ]

    description = "\n".join(desc_parts)
    expected_output = "请调用 emit_output 提交本步骤的结构化产物。"

    task = Task(description=description, expected_output=expected_output, agent=agent)

    main_loop = asyncio.get_running_loop()

    def _step_cb(s: object) -> None:
        # Heartbeat the parent task so the watchdog stays happy through
        # the whole Crew, not just the executor step.
        try:
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()
            asyncio.run_coroutine_threadsafe(
                crud.update_by_id("tasks", parent_task_id,
                                  {"last_activity_at": now_iso}),
                main_loop,
            )
        except Exception:
            pass
        text = _extract_step_text(s)
        if not text:
            return
        try:
            from api.ws import manager
            asyncio.run_coroutine_threadsafe(
                manager.broadcast("agent.output", {
                    "project_id": project_id,
                    "task_id": parent_task_id,
                    "agent_role": role,
                    "step": step_index,
                    "text": text,
                }),
                main_loop,
            )
        except Exception:
            pass

    crew = Crew(
        agents=[agent], tasks=[task],
        process=Process.sequential, verbose=False, memory=False,
        step_callback=_step_cb,
    )

    log.info("crew_step.start",
             parent_task=parent_task_id, step_index=step_index,
             step_role=step_role, agent_role=role, model=model_name)
    try:
        result = await asyncio.to_thread(crew.kickoff)
    except PermissionDenied as exc:
        log.warning("crew_step.permission_denied",
                    parent_task=parent_task_id, step=step_index, kind=exc.kind)
        return f"[PermissionDenied] {exc}", None

    output_text = str(result.raw if hasattr(result, "raw") else result)

    # Pull whatever the step emitted via emit_output (may be None if the
    # agent forgot to call it — orchestrator decides how to handle).
    from src.tools.builtin.local._output_capture import pop_output
    captured = pop_output(step_task_key)

    log.info("crew_step.finished",
             parent_task=parent_task_id, step_index=step_index,
             captured=captured is not None, output_len=len(output_text))
    return output_text, (captured if isinstance(captured, dict) else None)
