"""WriteBlueprintTool — Plan Maker writes the design dossier to `.mycrew/`.

Plan Maker calls this once after `create_workflow` + `assign_agents` are
done. The tool persists:

  <root>/.mycrew/blueprint.json     # machine-readable: project + all tasks
  <root>/.mycrew/architecture.md    # human-readable: Plan Maker's overview
  <root>/.mycrew/tasks/task_NN.md   # one per task: detail + acceptance hints

For iteration mode, the namespace is per-iteration so prior rounds don't
get overwritten:

  <root>/.mycrew/iter-002/blueprint.json
  ...

The QA Agent reads this directory (via `read_file_local` /
`list_directory_local`) when running the final review.

session_id is bound via factory at instantiation — the LLM never sees it
or the resolved root_path. If the project has no `root_path` set (creation
mode where user hasn't picked a folder yet), the tool stores the dossier
in `<project_workdir>/.mycrew_pending/` and the inception svc moves it to
the real root once root_path is supplied.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool

log = structlog.get_logger()


class TaskBlueprint(BaseModel):
    title: str
    detail: str = ""
    deps: list[int] = Field(default_factory=list)
    output_schema: dict = Field(default_factory=dict)
    kind: str = "regular"
    acceptance_notes: str = Field(
        "",
        description="Plan Maker's own notes on what 'done' looks like — QA reads this",
    )


class WriteBlueprintArgs(BaseModel):
    architecture_overview: str = Field(
        ...,
        description=(
            "Free-text architectural overview: project goals, core systems, "
            "data flow, key design decisions. Markdown allowed. Will be "
            "written to architecture.md verbatim."
        ),
    )
    tasks: list[TaskBlueprint] = Field(
        ...,
        description=(
            "Same task list submitted to create_workflow, plus an "
            "`acceptance_notes` field per task describing how QA should "
            "verify the deliverable."
        ),
    )


class WriteBlueprintTool(GuardedLocalTool):
    name: str = "write_blueprint"
    description: str = (
        "Persist your project design dossier to the project's .mycrew/ "
        "folder so the QA Agent can read it for verification. Call this "
        "ONCE after create_workflow + assign_agents, before ending your "
        "turn. Writes architecture.md + blueprint.json + tasks/task_NN.md."
    )
    args_schema: type[BaseModel] = WriteBlueprintArgs
    permission_kind: ClassVar[str | None] = "file_write"

    _bound_session_id: ClassVar[str] = ""

    def _run(self, architecture_overview: str, tasks: list[dict]) -> str:
        session_id = self._bound_session_id
        if not session_id:
            return "[Error] Internal: session_id not bound to write_blueprint."

        async def _do() -> str:
            from infra.repo import crud
            from bootstrap.paths import OUTPUT_DIR

            session = await crud.get_by_id("inception_sessions", session_id)
            if not session or not session.get("project_id"):
                return (
                    "[Error] No project bound to this session yet. Call "
                    "create_workflow first, then write_blueprint."
                )
            project_id = session["project_id"]
            project = await crud.get_by_id("projects", project_id)
            if not project:
                return f"[Error] project {project_id} not found."

            iteration_index = int(project.get("iteration_index") or 1)
            root_path = project.get("root_path") or ""

            # Pick output dir: real root_path/.mycrew/ if set, else a
            # pending location under OUTPUT_DIR. inception_svc will
            # migrate when the user finally sets root_path.
            if root_path:
                base = Path(root_path) / ".mycrew"
                if iteration_index > 1:
                    base = base / f"iter-{iteration_index:03d}"
                pending = False
            else:
                base = Path(OUTPUT_DIR) / project_id / ".mycrew_pending"
                pending = True

            try:
                base.mkdir(parents=True, exist_ok=True)
                (base / "tasks").mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                return f"[Error] failed to create .mycrew dir at {base}: {exc}"

            # blueprint.json — machine-readable
            blueprint = {
                "project_id": project_id,
                "project_name": project.get("name"),
                "iteration_index": iteration_index,
                "parent_project_id": project.get("parent_project_id"),
                "template_id": project.get("template_id"),
                "tasks": [
                    t.model_dump() if hasattr(t, "model_dump") else dict(t)
                    for t in tasks
                ],
            }
            (base / "blueprint.json").write_text(
                json.dumps(blueprint, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # architecture.md — human-readable overview
            (base / "architecture.md").write_text(
                architecture_overview, encoding="utf-8",
            )

            # tasks/task_NN.md — one per task with detail + acceptance notes
            task_dicts = blueprint["tasks"]
            for i, t in enumerate(task_dicts, start=1):
                slug = (t.get("title") or "task").replace("/", "_")[:40]
                fname = f"task_{i:02d}_{slug}.md"
                lines = [
                    f"# Task {i}. {t.get('title','')}",
                    "",
                    "## 详细指令",
                    t.get("detail", "(none)"),
                    "",
                    "## 输出 Schema",
                    "```json",
                    json.dumps(t.get("output_schema") or {},
                               ensure_ascii=False, indent=2),
                    "```",
                    "",
                    "## 验收要点 (QA 读这里)",
                    t.get("acceptance_notes") or "(none)",
                ]
                (base / "tasks" / fname).write_text(
                    "\n".join(lines), encoding="utf-8",
                )

            log.info("write_blueprint.ok",
                     project_id=project_id, dir=str(base),
                     task_count=len(task_dicts), pending=pending)

            location_hint = (
                f"<root_path>/.mycrew/" if not pending
                else "(pending — will move to <root>/.mycrew/ once user sets root_path)"
            )
            return (
                f"Blueprint written to {location_hint}. "
                f"{len(task_dicts)} task spec(s), architecture.md, blueprint.json."
            )

        try:
            return self._guarded_local(_do)
        except Exception as exc:
            log.error("write_blueprint.failed", error=str(exc),
                      session_id=session_id)
            return f"[Error] write_blueprint failed: {exc}"


def make_write_blueprint_tool(session_id: str) -> WriteBlueprintTool:
    class _Bound(WriteBlueprintTool):
        _bound_session_id: ClassVar[str] = session_id

    return _Bound()


__all__ = ["WriteBlueprintTool", "make_write_blueprint_tool"]
