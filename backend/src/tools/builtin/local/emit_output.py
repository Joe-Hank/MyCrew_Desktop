"""EmitOutput — universal structured-output tool for every execution Agent.

Why this exists
---------------
CrewAI is sequential: Task N+1 reads Task N's `output`. The task definition
carries an `output_schema` (JSON Schema), but currently the LLM only sees
that schema as a *hint inside the prompt* — there is no enforcement at the
function-call boundary, so the model frequently produces "looks like JSON
but not quite" text that fails downstream validation, stalling the run.

This tool turns the schema into a real function the LLM must call. The
`args_schema` requires a `payload: dict`; the tool validates `payload`
against the task's bound `output_schema`, stores it in
`_output_capture._outputs[task_id]` so `workflow_svc` can pick it up
directly, and returns either "validated OK" or a list of validation
errors. The LLM self-corrects until it passes.

Bound via factory at instantiation: the task_id + output_schema are
injected by the crewai_runner so the LLM only fills in the payload.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool
from src.tools.builtin.local._output_capture import set_output

log = structlog.get_logger()


# Field names that — when present in an emit_output payload — indicate the
# value should be a path to a file that the agent has just written. The
# tool verifies these files actually exist before accepting the output,
# closing the "I described a script but never wrote it" loophole the
# 心之回廊 audit (2026-05-13) surfaced.
_PATH_FIELD_NAMES = (
    "file_path", "filepath", "path",
    "image_path", "asset_path", "script_path",
    "output_path",
)


def _gather_paths(payload: Any, out: list[str]) -> None:
    """Recursively collect candidate file paths from a payload tree."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in _PATH_FIELD_NAMES and isinstance(v, str) and v.strip():
                out.append(v.strip())
            else:
                _gather_paths(v, out)
    elif isinstance(payload, list):
        for item in payload:
            _gather_paths(item, out)
    # `file_paths` (plural) → list of strings
    # already handled by the list branch above


class EmitOutputArgs(BaseModel):
    payload: dict = Field(
        ...,
        description=(
            "The final structured output for this task. Must match the "
            "task's declared output_schema (the JSON Schema shown in the "
            "task description). If output_schema is empty, any dict is "
            "accepted — wrap free-form text as {\"text\": \"...\"}."
        ),
    )


class EmitOutput(GuardedLocalTool):
    name: str = "emit_output"
    description: str = (
        "Submit the final structured output for THIS task. Call exactly "
        "once when your work is done. The payload is validated against "
        "the task's output schema; on failure the errors are returned so "
        "you can correct the payload and call again. Returns 'OK' on "
        "success — after that, end your turn with a one-line confirmation."
    )
    args_schema: type[BaseModel] = EmitOutputArgs
    # No permission_kind: this is pure data capture, no side-effects on
    # filesystem / network / shell. Audit event still fires via the base.
    permission_kind: ClassVar[str | None] = None

    _bound_task_id: ClassVar[str] = ""
    _bound_schema: ClassVar[dict] = {}
    # Project root for path-existence checks. Set by the factory; empty
    # disables the check (creation-mode tasks where root isn't bound yet).
    _bound_root: ClassVar[str] = ""

    def _run(self, payload: dict) -> str:
        task_id = self._bound_task_id
        schema = self._bound_schema or {}
        if not task_id:
            return "[Error] Internal: emit_output is not bound to a task."

        # Some LLMs pass the JSON as a string; tolerate it.
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                return (
                    "[ValidationError] payload must be a JSON object, not a "
                    "raw string. Wrap as {\"text\": \"...\"} if free-form."
                )
        if not isinstance(payload, dict):
            return f"[ValidationError] payload must be a JSON object (got {type(payload).__name__})."

        # Validate against the bound schema (no-op if schema is empty)
        from domain.qa.output_validator import validate_output_schema
        errors = validate_output_schema(payload, schema)
        if errors:
            joined = "; ".join(errors[:8])
            return (
                f"[ValidationError] output does not match schema: {joined}. "
                "Please correct the payload and call emit_output again."
            )

        # Path-existence check: any string under a *_path / path field is
        # treated as a project-relative path the agent claims to have
        # written. If the file isn't actually on disk, reject — this is
        # the wall against "described but never built" outputs.
        if self._bound_root:
            missing = self._verify_paths(payload)
            if missing:
                listed = ", ".join(missing[:6])
                more = f" (and {len(missing) - 6} more)" if len(missing) > 6 else ""
                return (
                    f"[ValidationError] payload references file_path(s) that "
                    f"do not exist on disk: {listed}{more}. You must actually "
                    "create these files first (use write_file / unity_write_file "
                    "/ comfy_enqueue_workflow etc.) and then re-call emit_output "
                    "with the real paths."
                )

        # Capture for workflow_svc to read after kickoff
        set_output(task_id, payload)
        log.info("emit_output.captured", task_id=task_id, keys=list(payload.keys())[:8])
        return "OK — output recorded. End your turn with a one-line confirmation."

    def _verify_paths(self, payload: dict) -> list[str]:
        """Return list of path strings that don't resolve to existing files
        under the bound project root. Empty list = all paths exist (or none
        were declared)."""
        candidates: list[str] = []
        _gather_paths(payload, candidates)
        if not candidates:
            return []
        root_p = Path(self._bound_root)
        missing: list[str] = []
        for rel in candidates:
            p = Path(rel)
            absolute = p if p.is_absolute() else (root_p / p)
            try:
                if not absolute.exists():
                    missing.append(rel)
            except Exception:
                missing.append(rel)
        return missing


def make_emit_output_tool(
    task_id: str,
    output_schema: dict | None,
    project_root: str | None = None,
) -> EmitOutput:
    """Factory: bind a task_id + output_schema (+ project root) to a fresh
    tool subclass.

    The LLM sees only `payload` in the function signature; task_id, schema
    and project_root are closure-bound so the model can't spoof them.

    project_root is used to verify any file_path/path values in the
    payload actually exist on disk before accepting the output.
    """
    schema = output_schema or {}
    root = project_root or ""

    class _Bound(EmitOutput):
        _bound_task_id: ClassVar[str] = task_id
        _bound_schema: ClassVar[dict] = schema
        _bound_root: ClassVar[str] = root

    return _Bound()


__all__ = ["EmitOutput", "make_emit_output_tool"]
