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
from typing import Any, ClassVar

import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool
from src.tools.builtin.local._output_capture import set_output

log = structlog.get_logger()


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

        # Capture for workflow_svc to read after kickoff
        set_output(task_id, payload)
        log.info("emit_output.captured", task_id=task_id, keys=list(payload.keys())[:8])
        return "OK — output recorded. End your turn with a one-line confirmation."


def make_emit_output_tool(task_id: str, output_schema: dict | None) -> EmitOutput:
    """Factory: bind a task_id + output_schema to a fresh tool subclass.

    The LLM sees only `payload` in the function signature; the task_id
    and schema are closure-bound here so the model can't spoof them.
    """
    schema = output_schema or {}

    class _Bound(EmitOutput):
        _bound_task_id: ClassVar[str] = task_id
        _bound_schema: ClassVar[dict] = schema

    return _Bound()


__all__ = ["EmitOutput", "make_emit_output_tool"]
