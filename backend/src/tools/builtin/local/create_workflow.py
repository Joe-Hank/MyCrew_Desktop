"""CreateWorkflowTool — Plan Maker's primary action.

The Plan Maker agent calls this tool when its task decomposition is
ready. The tool persists the workflow as a real Project + Tasks rows
and broadcasts `inception.workflow_created` so the frontend can show
an editable preview panel.

session_id is *bound* via factory at instantiation so the LLM does not
have to supply it — eliminating a class of "model invented an ID" errors.
"""
from __future__ import annotations

from typing import ClassVar

import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool

log = structlog.get_logger()

ALLOWED_EXECUTION_KINDS = {"sequential", "crew", "flow"}


class TaskSpec(BaseModel):
    """One row in the user-facing task list."""
    title: str = Field(..., description="Short task name")
    detail: str = Field("", description="Detailed task description (>= 1 sentence)")
    deps: list[int] = Field(
        default_factory=list,
        description="0-based indices of prerequisite tasks in this same list",
    )
    output_schema: dict = Field(
        default_factory=dict,
        description="JSON Schema describing this task's output; {} for free text",
    )
    kind: str = Field(
        "regular",
        description='"regular" or "final_qa" (auto-appended if missing)',
    )


class CreateWorkflowArgs(BaseModel):
    """Arguments the LLM provides. session_id is bound by the factory."""
    name: str = Field(..., description="Project name (concise, user-recognizable)")
    execution_kind: str = Field(
        "sequential",
        description="One of sequential / crew / flow",
    )
    tasks: list[TaskSpec] = Field(..., description="Ordered task list")


def _normalize_tasks(tasks: list[dict]) -> list[dict]:
    """Ensure a final_qa task exists; auto-append one depending on all terminal nodes."""
    out = [dict(t) for t in tasks]
    if any(t.get("kind") == "final_qa" for t in out):
        return out

    terminal = [
        i for i in range(len(out))
        if not any(i in t.get("deps", []) for t in out)
    ]
    out.append({
        "title": "质量检查",
        "detail": "对整个项目进行最终质量审查",
        "deps": terminal,
        "kind": "final_qa",
        "output_schema": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["pass", "warn", "fail"]},
                "overall_score": {"type": "number"},
                "issues": {"type": "array", "items": {"type": "object"}},
                "summary": {"type": "string"},
            },
            "required": ["verdict", "overall_score", "issues", "summary"],
        },
    })
    return out


class CreateWorkflowTool(GuardedLocalTool):
    """Base class for the bound factory instance. Do not register in
    crewai_runner registry — only Plan Maker instantiates it via factory."""

    name: str = "create_workflow"
    description: str = (
        "Persist a planned workflow as a real Project + Tasks. Returns "
        "the new project_id. Call this once your task plan is finalized."
    )
    args_schema: type[BaseModel] = CreateWorkflowArgs
    permission_kind: ClassVar[str | None] = "workflow_create"

    # Filled in by the factory
    _bound_session_id: ClassVar[str] = ""

    def _run(self, name: str, execution_kind: str, tasks: list[dict]) -> str:
        session_id = self._bound_session_id
        if not session_id:
            return "[Error] Internal error: session_id not bound to tool."

        if execution_kind not in ALLOWED_EXECUTION_KINDS:
            return f"[Error] invalid execution_kind: {execution_kind!r}. Use one of {sorted(ALLOWED_EXECUTION_KINDS)}."

        # Pydantic may have already coerced tasks to dicts; ensure shape.
        if not isinstance(tasks, list) or not tasks:
            return "[Error] tasks must be a non-empty list."
        try:
            task_dicts = [
                t.model_dump() if hasattr(t, "model_dump") else dict(t)
                for t in tasks
            ]
        except Exception as exc:
            return f"[Error] failed to normalize tasks: {exc}"

        async def _do() -> str:
            # Lazy imports — avoid loading the whole service graph at module import time
            from infra.repo import crud
            from services.project_svc import project_svc
            from api.ws import manager

            # Duplicate-call guard: refuse if this session is already bound
            session = await crud.get_by_id("inception_sessions", session_id)
            if session and session.get("project_id"):
                return (
                    f"[Error] Workflow already created for this session "
                    f"(project_id={session['project_id']}). "
                    "To regenerate, the frontend must delete it first."
                )

            normalized = _normalize_tasks(task_dicts)
            task_data = [{
                "title": t["title"],
                "detail": t.get("detail", ""),
                "kind": t.get("kind", "regular"),
                "output_schema": t.get("output_schema", {}),
                "deps": t.get("deps", []),
            } for t in normalized]

            project = await project_svc.create_project_with_tasks(
                data={"name": name, "execution_kind": execution_kind},
                tasks=task_data,
            )
            project_id = project["id"]

            await crud.update_by_id("inception_sessions", session_id, {
                "project_id": project_id,
            })

            blueprint = {
                "name": name,
                "execution_kind": execution_kind,
                "tasks": normalized,
            }
            await manager.broadcast("inception.workflow_created", {
                "session_id": session_id,
                "project_id": project_id,
                "project": project,
                "blueprint": blueprint,
            })

            log.info("create_workflow.persisted",
                     project_id=project_id, task_count=len(normalized),
                     session_id=session_id)
            return f"Workflow created. project_id={project_id}, tasks={len(normalized)}"

        try:
            return self._guarded_local(_do)
        except Exception as exc:
            log.error("create_workflow.failed", error=str(exc), session_id=session_id)
            return f"[Error] Failed to create workflow: {exc}"


def make_create_workflow_tool(session_id: str) -> CreateWorkflowTool:
    """Factory that binds a session_id to a fresh tool subclass.

    The Plan Maker LLM sees only `name / execution_kind / tasks` in its
    function signature — session_id is injected via the closure.
    """

    class _Bound(CreateWorkflowTool):
        _bound_session_id: ClassVar[str] = session_id

    instance = _Bound()
    # CrewAI inspects .name / .description / .args_schema; they're inherited.
    return instance
