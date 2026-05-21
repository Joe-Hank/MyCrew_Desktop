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


# ── CrewStructuredTool → BaseTool adapter (2026-05-16) ────────────
#
# CrewAI 1.14's Agent has a strict Pydantic check on `tools`: every entry
# must be an instance of `crewai.tools.BaseTool` (or a plain dict). Our
# Unity MCP wrappers are built as `CrewStructuredTool` instances — a
# sibling class that DOES NOT subclass BaseTool in this version. Result:
# any agent with a Unity tool in its tool_ids crashes at Agent(...) with
# "Input should be a valid dictionary or instance of BaseTool".
#
# Production trace: the 「祖玛」 Art Crew got to step 3 (Technical Artist
# has 7 Unity tools); the first call to Agent(tools=[...]) raised
# "7 validation errors for Agent: tools.5 ... CrewStructuredTool".
#
# Fix: a thin BaseTool subclass that delegates _run to the wrapped
# CrewStructuredTool's invoke(). All metadata (name/description/
# args_schema) is reused so the LLM sees the same surface. Idempotent —
# wrapping an already-BaseTool instance returns it unchanged.

def _adapt_to_base_tool(tool: Any) -> Any:
    """Return `tool` unchanged when it's already a BaseTool. Otherwise
    wrap it in a delegating subclass so Agent's Pydantic check passes."""
    from crewai.tools import BaseTool
    if isinstance(tool, BaseTool):
        return tool
    # Defensive — only adapt if it looks like a CrewStructuredTool
    # (or compatible: has name/description/args_schema/invoke).
    if not all(hasattr(tool, a) for a in ("name", "description", "invoke")):
        return tool

    class _Wrapped(BaseTool):
        name: str = tool.name
        description: str = tool.description
        # args_schema may be a Pydantic model class; BaseTool accepts that
        # exactly. None / falsy means "no schema" — leave it to BaseTool's
        # default (the parent's annotation is `type[BaseModel] | None`).
        args_schema: type | None = getattr(tool, "args_schema", None)

        def _run(self, *args: Any, **kwargs: Any) -> Any:
            # CrewStructuredTool.invoke takes a dict of args OR (per
            # langchain convention) a single positional argument. Forward
            # whichever shape we got — Agent always calls _run(**kwargs)
            # in current CrewAI, so kwargs is the common path.
            payload: dict[str, Any]
            if args and not kwargs and isinstance(args[0], dict):
                payload = args[0]
            else:
                payload = dict(kwargs)
            return tool.invoke(payload)

    return _Wrapped()


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
    thinking_mode: bool = False,
    supports_thinking: bool = False,
):
    """Build a `crewai.LLM` instance from a v3 provider row.

    Optional `temperature` + `max_tokens` are passed through to litellm
    when set — used by Plan Maker 2.0 sub-agents to tune per-intent
    output behavior (cheap classifier at temp=0 vs creative architect
    at temp=0.7, etc.).

    `thinking_mode` + `supports_thinking` together gate the provider-
    specific reasoning channel:
      - Anthropic Claude 3.7+ / 4.x: `thinking={"type":"enabled",
        "budget_tokens": N}` (forces temperature=1).
      - OpenAI o-series / gpt-5: `reasoning_effort="medium"`.
      - DeepSeek-reasoner / Qwen QwQ: model_name itself selects
        reasoning; we just don't send a `thinking` field they'd reject.
    The fan-out is gated on both flags so an Anthropic model without
    extended-thinking support (e.g. claude-3-5-haiku) never receives
    the `thinking` kwarg even if the user accidentally enabled the
    agent toggle.
    """
    from crewai import LLM

    ptype = (provider.get("type") or "openai").lower()
    model_string = _build_litellm_model_string(ptype, model_name)
    api_key = provider.get("api_key_ref") or None
    kwargs: dict[str, Any] = {
        "model": model_string,
        "api_key": api_key,
        # 2026-05-19 incident: CrewAI 1.14 puts "deepseek" / "ollama" /
        # "hosted_vllm" / "dashscope" / "openrouter" in its
        # SUPPORTED_NATIVE_PROVIDERS list — when matched, it uses a
        # native adapter that fails to round-trip OpenAI-style tool
        # calling for some of those providers (deepseek confirmed: tool
        # calls leak as DSML markup in message.content, captured=null).
        # LiteLLM handles all of them correctly. Forcing is_litellm=True
        # routes through the LiteLLM fallback path regardless of
        # provider — at the cost of a possibly slightly slower init,
        # which is irrelevant for an LLM call that takes seconds.
        "is_litellm": True,
    }
    base_url = provider.get("base_url")
    if base_url:
        kwargs["base_url"] = base_url

    # 2026-05-21 (Probe 1 finding): CrewAI 1.14's Converter / Instructor
    # path calls LiteLLM through a code path that does NOT inherit the
    # `api_key` kwarg from the `LLM(...)` instance — it relies on env
    # vars. When Task(output_pydantic=Spec) triggers Converter, every
    # internal LLM call fails with "Missing credentials" for dashscope /
    # deepseek. Bridge api_key to the provider-specific env var that
    # LiteLLM looks up. Safe: env is process-local; only set when api_key
    # is non-empty; never clobbers an existing env value.
    import os
    if api_key:
        env_keys = {
            "qwen":      "DASHSCOPE_API_KEY",
            "deepseek":  "DEEPSEEK_API_KEY",
            "openai":    "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        ev = env_keys.get(ptype)
        if ev and not os.environ.get(ev):
            os.environ[ev] = api_key
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    if max_tokens is not None:
        kwargs["max_tokens"] = int(max_tokens)

    if thinking_mode and supports_thinking:
        if ptype == "anthropic":
            # litellm passes `thinking` straight through to the Anthropic
            # messages API. Extended thinking requires temperature=1; if
            # the caller already set something else, override.
            budget = max(1024, min(int(kwargs.get("max_tokens", 4096)) - 1000, 10000))
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kwargs["temperature"] = 1.0
        elif ptype == "openai":
            # OpenAI reasoning models (o-series, gpt-5*) accept a
            # `reasoning_effort` knob. Default to medium — high doubles
            # latency and the planner phases don't need it.
            kwargs["reasoning_effort"] = "medium"
        # deepseek/qwen/gemini: nothing extra to send — picking the
        # reasoner variant of the model name is sufficient.

    return LLM(**kwargs)


async def _resolve_thinking_for_call(
    agent_row: dict | None,
    provider_id: str,
    model_name: str,
) -> tuple[bool, bool]:
    """Resolve `(thinking_mode_requested, model_supports_thinking)`
    for a single LLM call.

    - thinking_mode is read off the agent row (DB stores it 0/1).
    - supports_thinking is read off the matching llm_models row. If
      the row is missing or the cached value is false, the call goes
      out without `thinking` even when the agent toggle is on — same
      gating that the LLM editor enforces in the UI, applied
      server-side so an out-of-date toggle on an old agent can't
      crash a Claude 3.5 / GPT-4o request.

    Both returned as plain bools (DB stores 0/1)."""
    thinking_mode = bool((agent_row or {}).get("thinking_mode", 0))
    if not thinking_mode:
        return False, False
    rows = await crud.get_all(
        "llm_models",
        "provider_id = ? AND model_name = ?",
        (provider_id, model_name),
    )
    supports = bool(rows[0].get("supports_thinking", 0)) if rows else False
    return thinking_mode, supports


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
        # NOTE: mcp_filesystem.read_file / list_directory removed
        # 2026-05-16 — overlapped with local versions
        # (read_file_local / list_directory_local) which everyone uses;
        # no agent was assigned the MCP variants. Drop the imports too.
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
        from src.tools.builtin.local.verify_image_dimensions import (
            make_verify_image_dimensions_tool,
        )
        from src.tools.builtin.local.verify_outputs import (
            make_verify_outputs_tool,
        )
        from src.tools.builtin.mcp_git.tools import make_git_tools
        # Unity MCP — pre-instantiated CrewStructuredTool instances
        from src.tools.builtin.unity import TOOL_MAP as UNITY_TOOL_MAP
    except Exception as exc:
        log.warning("crewai_runner.tool_import_failed", error=str(exc))
        return instances

    # MCP / context-free tool classes — instantiate per-call
    static_registry = {
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
        # output capture. `step_role` propagates so head steps (which
        # only emit specs and don't have write tools) skip the on-disk
        # path-existence check — see make_emit_output_tool docstring.
        "emit_output": lambda: make_emit_output_tool(
            ctx.get("task_id") or "",
            ctx.get("output_schema") or {},
            ctx.get("project_root"),
            ctx.get("output_paths") or None,
            step_role=ctx.get("step_role"),
        ),
        # 8-bit audio synthesis (Audio Crew executor)
        "synth_8bit_sfx": lambda: make_synth_8bit_sfx_tool(ctx.get("project_root")),
        # Image dimension verification (Art / UI Crew QA + Generator)
        "verify_image_dimensions": lambda: make_verify_image_dimensions_tool(
            ctx.get("project_root"),
        ),
        # Layer 2 (2026-05-21): path-existence self-check for steps that
        # use Task(output_pydantic=Spec). The agent calls this once near
        # the end to confirm files declared in its Spec actually exist.
        # Bound to project_root + PM-declared output_paths so it doubles
        # as a contract cross-check.
        "verify_outputs": lambda: make_verify_outputs_tool(
            project_root=ctx.get("project_root") or "",
            expected_paths=ctx.get("output_paths") or None,
        ),
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
                instances.append(_adapt_to_base_tool(static_registry[n]()))
            elif n in bound_registry:
                instances.append(_adapt_to_base_tool(bound_registry[n]()))
            elif n in UNITY_TOOL_MAP:
                # Unity MCP tools are pre-instantiated singletons (stateless
                # bridge wrappers — safe to share across agents). They're
                # CrewStructuredTool instances; _adapt wraps them in a
                # BaseTool delegate so Agent's Pydantic check passes.
                instances.append(_adapt_to_base_tool(UNITY_TOOL_MAP[n]))
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

    thinking_mode, supports_thinking = await _resolve_thinking_for_call(
        agent_row, provider_id, model_name,
    )
    llm = _build_crewai_llm(
        provider, model_name,
        thinking_mode=thinking_mode,
        supports_thinking=supports_thinking,
    )

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

    # ── Token accounting (CrewAI bypasses our gateway, so we read its
    # own UsageMetrics after kickoff). Best-effort: anything that goes
    # wrong here must not break the task output.
    try:
        await _record_crew_usage(
            crew_obj=crew,
            project_id=project_id,
            session_id=None,
            provider_id=provider_id,
            model_name=model_name,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("crewai_runner.metrics_failed",
                    task_id=task_input.task_id, error=str(exc))

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
    parent_code_contract: dict | None,
    upstream_outputs: dict,
    prev_step_payload: dict | None,
    provider_id: str,
    model_name: str,
    crew_name: str = "",            # 2026-05-21: needed for spec_for() lookup
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

    thinking_mode, supports_thinking = await _resolve_thinking_for_call(
        agent_row, provider_id, model_name,
    )

    # 2026-05-21: read max_tokens from llm_models row. Previously the
    # runtime Crew path passed nothing → LiteLLM used provider default
    # (~1500 tok for dashscope), which truncated System Designer's
    # multi-file spec mid-string and starved rescue (raw_text was
    # unbalanced JSON, _rescue_react_emit_output couldn't recover).
    # If the column is NULL we still send nothing (preserves prior
    # behaviour for providers where the default is fine).
    runtime_max_tokens: int | None = None
    rows = await crud.get_all(
        "llm_models", "provider_id = ? AND model_name = ?",
        (provider_id, model_name),
    )
    if rows and rows[0].get("max_tokens"):
        try:
            runtime_max_tokens = int(rows[0]["max_tokens"])
        except (TypeError, ValueError):
            runtime_max_tokens = None

    llm = _build_crewai_llm(
        provider, model_name,
        thinking_mode=thinking_mode,
        supports_thinking=supports_thinking,
        max_tokens=runtime_max_tokens,
    )

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
        # 2026-05-20: propagate step_role so emit_output factory can
        # skip the on-disk path-existence check for Head steps (which
        # only emit specs and don't have write tools).
        "step_role": step_role,
    }
    tools = await _resolve_agent_tools(agent_row, tool_ctx)

    # 2026-05-21 Layer 2: auto-inject verify_outputs into agent tool set
    # for any executor/QA step in a registered Crew. Tool is bound to
    # project_root + PM-declared output_paths so it doubles as a contract
    # cross-check. Attached here (not in DB tool_ids) so the existing
    # seed_crews bindings don't need a migration during gradual rollout.
    # Skipped for Head steps (Head writes specs, not files).
    #
    # Originally gated on output_pydantic being wired, but Phase 4
    # variant probe (2026-05-21) ruled out output_pydantic — the gate
    # now matches the Layer 3 provider+spec routing instead: any non-
    # DeepSeek step that has a spec registered gets verify_outputs.
    _wants_verify = (
        crew_name
        and step_role != "head"
        and (provider or {}).get("type", "").lower() != "deepseek"
    )
    try:
        from domain.crew_specs import spec_for as _spec_lookup
        _wants_verify = bool(
            _wants_verify
            and _spec_lookup(crew_name, step_role) is not None
        )
    except ImportError:
        _wants_verify = False
    if _wants_verify:
        try:
            from src.tools.builtin.local.verify_outputs import (
                make_verify_outputs_tool,
            )
            existing_names = {
                getattr(t, "name", "") for t in tools if t is not None
            }
            if "verify_outputs" not in existing_names:
                vo = make_verify_outputs_tool(
                    project_root=project_root or "",
                    expected_paths=parent_output_paths or None,
                )
                tools.append(_adapt_to_base_tool(vo))
                log.info("crew_step.verify_outputs_injected",
                         parent_task=parent_task_id, step_index=step_index)
        except Exception as exc:  # noqa: BLE001
            log.warning("crew_step.verify_outputs_inject_failed",
                        parent_task=parent_task_id, error=str(exc))

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

    # 2026-05-18: Inject the PM-level code_contract so Executors know the
    # exact public symbols they must implement. Previously contract was
    # only checked post-Crew in workflow_svc._verify_code_contract — the
    # agent never saw it, so it implemented from Head spec alone and
    # routinely missed 3-5 signatures out of 12+. With the contract in
    # view, the agent has a precise checklist + can self-audit via
    # find_in_file before emit_output.
    if parent_code_contract:
        files = parent_code_contract.get("files") or []
        total_exports = sum(len(f.get("exports") or []) for f in files)
        if total_exports > 0:
            contract_lines: list[str] = [
                "",
                "## 🔴 代码契约（PM 已钉死，逐条实现 + 自审）",
                (
                    f"本 task 共有 **{total_exports} 个 public 符号必须出现在产出的 "
                    f".cs 文件中**，缺一个 → task 整体 validation_failed → "
                    "下游 task 阻塞。逐条核对，不要 // TODO 占位，不要"
                    "因 max_iter / max_tokens 提前停。"
                ),
            ]
            ns = parent_code_contract.get("namespace")
            if ns:
                contract_lines.append(f"- 推荐 namespace：`{ns}`（统一用这个）")
            for f in files:
                path = f.get("path") or "(unknown)"
                exports = f.get("exports") or []
                contract_lines.append(f"")
                contract_lines.append(
                    f"### `{path}` — {len(exports)} 个符号"
                )
                for e in exports:
                    kind = e.get("kind") or "?"
                    sig = e.get("signature") or ""
                    contract_lines.append(f"  - `[{kind}]` {sig}")
            imports = parent_code_contract.get("imports") or []
            if imports:
                contract_lines.append("")
                contract_lines.append(
                    "### 上游引用（你需要 using / using static 才能跨文件调用）"
                )
                for imp in imports:
                    uses = imp.get("uses") or []
                    contract_lines.append(
                        f"  - 来自 task_index={imp.get('from_task_index')}：{', '.join(uses)}"
                    )
            if step_role == "executor":
                contract_lines += [
                    "",
                    "### 执行步骤要求",
                    "1. 用 create_script / script_apply_edits 落 .cs 文件",
                    "2. **emit_output 之前**，对每个 .cs 文件用 find_in_file "
                    "把上面列的每条 signature 字符串都 grep 一遍",
                    "3. 任一 signature 缺失 → 用 script_apply_edits / "
                    "apply_text_edits 补上，再回第 2 步",
                    "4. 全部覆盖才 emit_output",
                ]
            elif step_role == "qa":
                contract_lines += [
                    "",
                    "### QA 步骤要求",
                    "对契约里每个 signature 调 find_in_file 验证。"
                    "缺一即 verdict='fail'，issues 必须列出具体缺失的符号。",
                ]
            desc_parts += contract_lines
    # 2026-05-17 Plan D fallback: when PM Phase 4 lost the output_paths
    # (legacy data from before the project_svc INSERT fix, or a Phase 4
    # LLM that came up empty), the Executor will read "[]" and exit
    # without producing any files — that's exactly how the 魔塔 audio
    # task ended up with zero .wav. Rather than punt, instruct the agent
    # to derive the must-produce list from task.detail prose. The fail
    # path is also explicit so the QA chain can surface unrecoverable
    # contracts.
    if not parent_output_paths and step_role in ("head", "executor"):
        desc_parts += [
            "",
            "## ⚠️ output_paths 缺失 — 从 detail 推导",
            (
                "PM 契约的 output_paths 为空数组。这通常是上游 PM 阶段的"
                "历史数据 bug；不要把它当成『无须产出文件』。请仔细阅读"
                "上方 task.detail，提取里面列出/暗示的所有应产出文件路径"
                "（包括相对项目根的 Assets/... 等），作为本步骤的 must-"
                "produce 清单，然后真正生成这些文件并在 emit_output 的 "
                "file_paths 字段里把它们全部列齐。"
            ),
            (
                "若 detail 中信息确实不足以推出任何路径，请用 emit_output "
                "提交 verdict='fail' + issues=['PM contract missing "
                "output_paths and detail is too vague to recover']，不要"
                "随便提交一个空 file_paths 就算完事。"
            ),
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

    # 2026-05-21 Layer 2 runtime injection: when verify_outputs was
    # auto-attached to the agent's tools, the step_instructions in
    # seed_crews don't mention it (those instructions are stable; we
    # don't migrate every Crew at once). Add a short runtime clause so
    # Qwen knows the tool is there and the expected protocol. Without
    # this clause the agent sees verify_outputs in its tool list but no
    # signal to invoke it — empirically the agent does call it once
    # told to (Phase 4 no_pydantic: 5/5 trials called verify_outputs).
    if _wants_verify:
        desc_parts += [
            "",
            "## 🛡️ 落盘自检（强制）",
            (
                "在调用 emit_output **之前**，必须调一次 verify_outputs(file_paths=[...]) "
                "把你声明的产物路径全部 verify。返回 OK 才能 emit_output；如果某文件还没写，"
                "先用 create_script / write_file / Unity MCP 工具真补，再 verify。"
                "**Server-side 还会再次校验磁盘真相**，编了不写 = task 失败。"
            ),
        ]

    description = "\n".join(desc_parts)
    expected_output = "请调用 emit_output 提交本步骤的结构化产物。"

    # 2026-05-21 Phase 4 finding (REVERTED Layer 1's output_pydantic):
    # We initially wired `Task(output_pydantic=Spec)` to let CrewAI's
    # Converter own schema enforcement. Probe 1 showed Qwen produces
    # the Spec correctly 10/10 in isolation, so this looked safe. The
    # Phase 4 variant probe revealed the deeper failure mode:
    # `output_pydantic` short-circuits Qwen's tool-use loop — the agent
    # interprets "produce a Spec" as terminal and skips ALL tools 5/5
    # trials. No prompt, max_iter, or tool-list variation can recover
    # tool engagement once output_pydantic is set. Without files written,
    # the Layer 2 disk truth check fails the task — net regression vs
    # the pre-refactor architecture.
    #
    # Fix: drop output_pydantic from runtime Crew tasks. crew_specs.py
    # is retained for (a) documentation of the per-step Pydantic
    # contract, and (b) future server-side validation of the captured
    # payload (orthogonal to how it's captured). The captured-payload
    # path stays on the legacy emit_output flow PLUS the new
    # verify_outputs tool (auto-injected above) PLUS the workflow_svc
    # server-side disk truth check. Qwen routing (Layer 3) and the
    # rescue layer (Layer 4) remain.
    task_output_pydantic = None  # kept for the read-back branch below
    task = Task(
        description=description,
        expected_output=expected_output,
        agent=agent,
    )

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

    # Token accounting for this step. Same caveats as run_task_with_crewai
    # above — best-effort, never breaks the caller.
    try:
        await _record_crew_usage(
            crew_obj=crew,
            project_id=project_id,
            session_id=None,
            provider_id=provider_id,
            model_name=model_name,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("crew_step.metrics_failed",
                    parent_task=parent_task_id, step=step_index,
                    error=str(exc))

    # 2026-05-21 Layer 1: when output_pydantic was wired, framework's
    # Converter already coerced agent output into the Spec. Read it
    # directly — bypasses the "agent forgot to call emit_output" 0/5
    # problem we measured on every provider/path combination.
    #
    # Three sources tried in order:
    #   1. task.output.pydantic.model_dump() — Layer 1 path (preferred)
    #   2. _output_capture pop/peek — legacy emit_output path
    #   3. None — workflow_svc takes over with rescue / halt logic
    captured: dict | None = None
    if task_output_pydantic is not None:
        try:
            task_output = getattr(task, "output", None)
            pyd = getattr(task_output, "pydantic", None) if task_output else None
            if pyd is not None:
                captured = pyd.model_dump()
                log.info("crew_step.captured_via_pydantic",
                         parent_task=parent_task_id, step_index=step_index,
                         keys=list(captured.keys())[:8])
        except Exception as exc:
            log.warning("crew_step.pydantic_read_failed",
                        parent_task=parent_task_id, step_index=step_index,
                        error=str(exc)[:200])

    if captured is None:
        # Legacy emit_output path. For QA the step_task_key collapses
        # to parent_task_id (so workflow_svc's downstream
        # pop_output(parent_task_id) finds the verdict). If we *popped*
        # here, the second pop in workflow_svc would return None, the
        # runner would fall through to JSON-text extraction, fail to
        # parse the Chinese summary, and raise a misleading
        # "'<schema field>' is a required property" error. Peek
        # instead — workflow_svc owns the final removal.
        from src.tools.builtin.local._output_capture import (
            peek_output, pop_output,
        )
        if step_task_key == parent_task_id:
            captured = peek_output(step_task_key)
        else:
            captured = pop_output(step_task_key)

    log.info("crew_step.finished",
             parent_task=parent_task_id, step_index=step_index,
             captured=captured is not None, output_len=len(output_text))
    return output_text, (captured if isinstance(captured, dict) else None)


# ── Token accounting helper ───────────────────────────────────────
#
# CrewAI 1.14 doesn't route through our LlmGateway — kickoff() drives
# litellm directly — so usage doesn't flow through gateway.chat()'s
# metrics hook. We instead read `crew.usage_metrics` (a UsageMetrics
# pydantic model) AFTER kickoff returns. The attribute name varies by
# version; we look at both `usage_metrics` and `token_usage`. When
# neither is present (older / newer than tested) we silently bail —
# this is a "nice to have"-class hook, never a hard requirement.

async def _record_crew_usage(
    *,
    crew_obj: Any,
    project_id: str | None,
    session_id: str | None,
    provider_id: str,
    model_name: str,
) -> None:
    """Pull (prompt, completion) tokens off a Crew after kickoff and hand
    them to metrics_svc. No-op when neither project_id nor session_id is
    set, or when CrewAI didn't surface usage."""
    if not project_id and not session_id:
        return
    usage = getattr(crew_obj, "usage_metrics", None) \
        or getattr(crew_obj, "token_usage", None)
    if usage is None:
        return
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    if prompt <= 0 and completion <= 0:
        return
    try:
        from services import metrics_svc
        await metrics_svc.record_llm_usage(
            project_id=project_id, session_id=session_id,
            provider_id=provider_id, model_name=model_name,
            prompt_tokens=prompt, completion_tokens=completion,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("crewai_runner.record_usage_failed", error=str(exc))
