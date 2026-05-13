"""AssignAgentsTool — Plan Maker's second action.

Role-keyword default tool binding
---------------------------------
When the LLM creates a NEW agent (new_agent spec), this tool also picks
a sensible default toolset based on keywords in the role name. The
mapping is intentionally generous — extra tools never hurt; missing
tools make 47% of agents incapable of producing real artifacts (see
the audit dated 2026-05-13). Every agent gets `emit_output` +
`write_file` + `read_file_local` at minimum so structured output and
basic disk I/O are always possible.


Called immediately after `create_workflow` has persisted the project +
tasks. The Plan Maker LLM provides a per-task mapping: either pick an
existing agent (by id) or supply a new-agent spec the tool persists and
binds. This is what turns a Plan Maker draft into a runnable project —
the workflow_svc start path requires every task to have an agent_id.

session_id is bound via factory at instantiation; the LLM only fills in
the assignments list, never the session id.
"""
from __future__ import annotations

import json
from typing import ClassVar

import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool

log = structlog.get_logger()


# ── Role-keyword → default tool names ──────────────────────────────
# Ordered: first match wins. Tools listed here will be looked up in
# the `tools` table at agent creation time and the resolved ids bound
# to the new agent's `tool_ids`. Universal tools (emit_output, write_file,
# read_file_local) are always added on top.

_UNIVERSAL_TOOLS = ["emit_output", "write_file", "mkdir", "read_file_local", "list_directory_local"]

_ROLE_TOOL_RULES: list[tuple[tuple[str, ...], list[str]]] = [
    # Unity programming roles — add git for VCS workflow
    (("unity developer", "unity programmer", "client engineer", "技术美术",
      "technical artist", "unity 客户端", "gameplay"),
     ["unity_read_file", "unity_write_file", "unity_delete_file",
      "unity_list_files",
      "git_status", "git_log", "git_diff_unstaged",
      "git_add", "git_commit",
      "tavily_search"]),
    # Blender / 3D / animation — full Blender toolset
    (("3d modeler", "modeller", "animator", "vfx artist",
      "blender", "rigger"),
     ["execute_blender_code", "get_scene_info", "get_object_info",
      "get_viewport_screenshot",
      "search_polyhaven_assets", "download_polyhaven_asset", "set_texture",
      "generate_hyper3d_model_via_text", "poll_rodin_job_status",
      "import_generated_asset",
      "tavily_search"]),
    # Image generation — ComfyUI flow + research
    (("comfyui", "image generator", "diffusion", "stable diffusion"),
     ["comfy_create_workflow_from_template", "comfy_validate_workflow",
      "comfy_enqueue_workflow", "comfy_get_job_status",
      "comfy_get_history", "comfy_list_local_models",
      "comfy_list_output_images", "comfy_upload_image",
      "tavily_search"]),
    # Concept Artist — ComfyUI light + research
    (("concept artist",),
     ["comfy_create_workflow_from_template", "comfy_enqueue_workflow",
      "comfy_get_job_status", "comfy_get_history",
      "comfy_list_output_images", "tavily_search", "tavily_extract"]),
    # UI / Design — Figma + research
    (("ui/ux", "ui designer", "ux", "interface designer"),
     ["figma_get_design_context", "figma_get_screenshot",
      "figma_get_metadata", "figma_get_variable_defs",
      "tavily_search"]),
    # Art Director — Figma read-only + research
    (("art director",),
     ["figma_get_design_context", "figma_get_screenshot",
      "figma_get_metadata", "tavily_search", "tavily_extract"]),
    # Project structure / inspection / QA — read tools + git history
    (("project structure", "structure manager", "qa engineer", "qa-agent",
      "reviewer"),
     ["unity_read_file", "unity_list_files",
      "git_status", "git_log", "git_diff_unstaged", "git_diff_staged"]),
    # System Designer — diagram + research
    (("system designer",),
     ["figma_generate_diagram", "tavily_research", "tavily_search",
      "tavily_extract"]),
    # Narrative / Audio / others — research + universal
    # NOTE: "project manager" removed from this list — Plan Maker owns
    # architectural planning itself; creating a PM execution agent is
    # explicitly forbidden (see _FORBIDDEN_ROLE_KEYWORDS below).
    (("narrative", "level designer",
      "audio designer", "sound designer"),
     ["tavily_search", "tavily_extract", "tavily_research"]),
]

# Roles Plan Maker is NOT allowed to create as a new execution agent.
# Plan Maker handles project-level planning directly (analysis, milestones,
# architecture). Pushing it into a post-execution agent was the root cause
# of the "described but never built" pattern surfaced in the 心之回廊 audit.
_FORBIDDEN_ROLE_KEYWORDS = (
    "project manager", "项目经理", "pm agent", "pm-agent",
)


def _role_is_forbidden(role: str) -> bool:
    r = (role or "").lower()
    return any(kw in r for kw in _FORBIDDEN_ROLE_KEYWORDS)


def _pick_default_tools(role: str) -> list[str]:
    """Return the default tool-name list for a newly-created agent."""
    r = (role or "").lower()
    extras: list[str] = []
    for kws, tools in _ROLE_TOOL_RULES:
        if any(kw in r for kw in kws):
            extras = tools
            break
    # De-dup while preserving order, universal tools first
    seen: set[str] = set()
    out: list[str] = []
    for n in _UNIVERSAL_TOOLS + extras:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


async def _resolve_tool_ids_by_name(names: list[str]) -> list[str]:
    """Look up tool_ids for the given tool names. Unknown names skipped."""
    from infra.repo import crud
    ids: list[str] = []
    for n in names:
        rows = await crud.get_all("tools", "name = ?", (n,))
        if rows:
            ids.append(rows[0]["id"])
        else:
            log.info("assign_agents.tool_not_seeded", name=n)
    return ids


class NewAgentSpec(BaseModel):
    role: str = Field(..., description="Concise role name, e.g. 'Unity 客户端工程师'")
    goal: str = Field("", description="One-paragraph objective summary")
    backstory: str = Field("", description="Optional context / persona")


class Assignment(BaseModel):
    """One task → one agent. Provide exactly one of `existing_agent_id`
    or `new_agent`. `task_index` is 0-based into the project's task list
    (insertion order matching the create_workflow call)."""
    task_index: int = Field(..., description="0-based task index in the project")
    existing_agent_id: str | None = Field(
        None,
        description="Existing agent id to reuse. Mutually exclusive with new_agent.",
    )
    new_agent: NewAgentSpec | None = Field(
        None,
        description="Spec for a brand new agent to create. Mutually exclusive with existing_agent_id.",
    )


class AssignAgentsArgs(BaseModel):
    assignments: list[Assignment] = Field(
        ...,
        description="One entry per task. Every task should be covered.",
    )


class AssignAgentsTool(GuardedLocalTool):
    name: str = "assign_agents"
    description: str = (
        "Bind an agent to every task of the just-created project. For each "
        "task, either reuse an existing agent (existing_agent_id) or create "
        "a new one (new_agent). Returns a summary listing the bindings + "
        "the agents that were newly created. Must be called once after "
        "create_workflow so the project is startable."
    )
    args_schema: type[BaseModel] = AssignAgentsArgs
    permission_kind: ClassVar[str | None] = "workflow_create"

    _bound_session_id: ClassVar[str] = ""

    def _run(self, assignments: list[dict]) -> str:
        session_id = self._bound_session_id
        if not session_id:
            return "[Error] Internal error: session_id not bound to tool."
        if not isinstance(assignments, list) or not assignments:
            return "[Error] assignments must be a non-empty list."

        try:
            norm = [
                a.model_dump() if hasattr(a, "model_dump") else dict(a)
                for a in assignments
            ]
        except Exception as exc:
            return f"[Error] failed to normalize assignments: {exc}"

        async def _do() -> str:
            from infra.repo import crud
            from api.ws import manager

            # Look up the bound session → project
            session = await crud.get_by_id("inception_sessions", session_id)
            if not session or not session.get("project_id"):
                return (
                    "[Error] No project bound to this session yet — "
                    "call create_workflow first."
                )
            project_id = session["project_id"]

            # Load tasks in insertion order (DB rowid)
            tasks = await crud.get_all("tasks", "project_id = ?", (project_id,))
            if not tasks:
                return f"[Error] Project {project_id} has no tasks."

            # Resolve a fallback LLM for new agents — prefer the session's
            # bound LLM, fall back to the first configured provider.
            default_llm_id = await _resolve_default_llm_id(session)

            # Apply each assignment
            results: list[str] = []
            created_agents: list[dict] = []
            for a in norm:
                idx = a.get("task_index")
                if not isinstance(idx, int) or idx < 0 or idx >= len(tasks):
                    results.append(f"  · skip: invalid task_index {idx}")
                    continue
                task = tasks[idx]

                existing_id = a.get("existing_agent_id")
                new_spec = a.get("new_agent")

                if existing_id:
                    # Validate the agent exists
                    found = await crud.get_by_id("agents", existing_id)
                    if not found:
                        results.append(
                            f"  · skip task #{idx}: agent {existing_id} not found",
                        )
                        continue
                    await crud.update_by_id("tasks", task["id"], {
                        "agent_id": existing_id,
                    })
                    results.append(
                        f"  · task #{idx} ({task.get('title','?')}) → "
                        f"existing agent {found.get('role','?')}",
                    )
                    continue

                if new_spec:
                    role_name = new_spec.get("role", "Assistant")

                    # Refuse to create a Project-Manager-style execution
                    # agent. Plan Maker should be doing this planning work
                    # itself, in architecture.md / blueprint.json.
                    if _role_is_forbidden(role_name):
                        results.append(
                            f"  · refuse task #{idx}: role '{role_name}' is "
                            "forbidden as an execution agent (Plan Maker "
                            "must own architectural planning directly; "
                            "write it into write_blueprint instead)"
                        )
                        continue

                    # Pick default tools by role keyword + resolve ids
                    default_tool_names = _pick_default_tools(role_name)
                    default_tool_ids = await _resolve_tool_ids_by_name(default_tool_names)

                    new_row = await crud.insert("agents", {
                        "role": role_name,
                        "goal": new_spec.get("goal", ""),
                        "backstory": new_spec.get("backstory", ""),
                        "reasoning": 0,
                        "max_retry": 3,
                        "memory_enabled": 0,
                        "memory_path": None,
                        "thinking_mode": 0,
                        "tool_ids": json.dumps(default_tool_ids),
                        "llm_id": default_llm_id,
                        "is_auto_generated": 1,
                    }, id_prefix="agent_")
                    created_agents.append(new_row)
                    await crud.update_by_id("tasks", task["id"], {
                        "agent_id": new_row["id"],
                    })
                    results.append(
                        f"  · task #{idx} ({task.get('title','?')}) → "
                        f"NEW agent {new_row.get('role','?')}",
                    )
                    continue

                results.append(
                    f"  · skip task #{idx}: neither existing_agent_id nor new_agent supplied",
                )

            # Broadcast for the frontend (drawer can announce created agents)
            await manager.broadcast("inception.agents_assigned", {
                "session_id": session_id,
                "project_id": project_id,
                "created_agents": [
                    {"id": a["id"], "role": a.get("role", "?")}
                    for a in created_agents
                ],
            })

            summary_lines = [
                f"Assigned {len(results)} task(s); created {len(created_agents)} new agent(s).",
                *results,
            ]
            if created_agents:
                names = ", ".join(a.get("role", "?") for a in created_agents)
                summary_lines.append(f"New agents: {names}")
            log.info("assign_agents.done",
                     session_id=session_id, project_id=project_id,
                     created=len(created_agents), assigned=len(results))
            return "\n".join(summary_lines)

        try:
            return self._guarded_local(_do)
        except Exception as exc:
            log.error("assign_agents.failed", error=str(exc), session_id=session_id)
            return f"[Error] Failed to assign agents: {exc}"


async def _resolve_default_llm_id(session: dict) -> str | None:
    """Pick a sensible default llm_id for a freshly-created agent.

    Prefer the inception session's bound LLM (the user already picked it
    when they opened Plan Maker); fall back to the first configured
    provider's first model. None if neither exists.
    """
    sid = session.get("llm_id")
    if isinstance(sid, str) and sid:
        return sid

    from infra.repo import crud
    providers = await crud.get_all("llm_providers")
    if not providers:
        return None
    first = providers[0]
    models = await crud.get_all("llm_models", "provider_id = ?", (first["id"],))
    if not models:
        return first["id"]  # provider id without model — won't run but at least bound
    return f"{first['id']}:{models[0]['model_name']}"


def make_assign_agents_tool(session_id: str) -> AssignAgentsTool:
    class _Bound(AssignAgentsTool):
        _bound_session_id: ClassVar[str] = session_id

    return _Bound()


# Keep deps array consistent — alias used by inception_svc when constructing
# the Plan Maker agent's toolset.
__all__ = [
    "AssignAgentsTool",
    "make_assign_agents_tool",
]
