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
    "file_paths", "filepaths", "paths",
    "image_path", "asset_path", "script_path",
    "output_path", "output_paths",
)


def _gather_paths(payload: Any, out: list[str]) -> None:
    """Recursively collect candidate file paths from a payload tree.

    Singular keys (file_path, image_path, ...) expect a string value.
    Plural keys (file_paths, output_paths, ...) expect a list of strings.
    The PM v4 「霓虹攀升」 incident exposed that the prior version only
    matched the singular forms, letting agents submit nine sprite paths
    in `file_paths` and pass validation with zero file checks.
    """
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in _PATH_FIELD_NAMES:
                if isinstance(v, str) and v.strip():
                    out.append(v.strip())
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str) and item.strip():
                            out.append(item.strip())
                else:
                    _gather_paths(v, out)
            else:
                _gather_paths(v, out)
    elif isinstance(payload, list):
        for item in payload:
            _gather_paths(item, out)


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
    # Stage E (2026-05-16): explicit list of files this task is contracted
    # to produce. Independent of payload field names — the agent could
    # report them under any key (or omit them) and this still verifies.
    # Empty list = "no files expected"; default empty disables the check.
    _bound_expected_paths: ClassVar[tuple[str, ...]] = ()

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

        # Path-existence check: agents must not claim files that aren't
        # really on disk. Two layers:
        #
        #   1. Bound contract (Stage E, 2026-05-16) — when the PM declared
        #      task.output_paths, every one of those paths must exist
        #      regardless of where the agent put them in the payload.
        #      This catches the schema-field-name bypass: the old
        #      heuristic walked payload looking for keys in a hard-coded
        #      whitelist; an agent using a custom field (e.g.
        #      "generated_files") could ship phantom paths past it.
        #
        #   2. Heuristic — recursively scan payload for whitelisted path
        #      fields. Still useful as defence in depth for tasks with
        #      no PM-declared output_paths (iterate flow, legacy rows).
        if self._bound_root:
            missing_contract = self._verify_expected_paths()
            if missing_contract:
                listed = ", ".join(missing_contract[:6])
                more = (
                    f" (and {len(missing_contract) - 6} more)"
                    if len(missing_contract) > 6 else ""
                )
                return (
                    f"[ValidationError] task.output_paths declares files "
                    f"that do not exist on disk yet: {listed}{more}. The "
                    "PM contract says these must be produced before you "
                    "call emit_output — actually create them first (use "
                    "write_file / unity_write_file / comfy_enqueue_workflow "
                    "etc.) and try again."
                )

            missing_payload = self._verify_paths(payload)
            if missing_payload:
                listed = ", ".join(missing_payload[:6])
                more = (
                    f" (and {len(missing_payload) - 6} more)"
                    if len(missing_payload) > 6 else ""
                )
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
        return self._missing_paths(candidates)

    def _verify_expected_paths(self) -> list[str]:
        """Same shape as _verify_paths but reads from the PM-declared
        ``task.output_paths`` contract bound by the factory. Empty
        contract = nothing to check."""
        if not self._bound_expected_paths:
            return []
        return self._missing_paths(list(self._bound_expected_paths))

    def _missing_paths(self, candidates: list[str]) -> list[str]:
        if not candidates:
            return []
        root_p = Path(self._bound_root)
        missing: list[str] = []
        for rel in candidates:
            if not isinstance(rel, str) or not rel.strip():
                continue
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
    expected_paths: list[str] | None = None,
) -> EmitOutput:
    """Factory: bind a task_id + output_schema (+ project root + PM's
    must-produce file list) to a fresh tool subclass.

    The LLM sees only `payload` in the function signature; everything
    else is closure-bound so the model can't spoof them.

    ``expected_paths`` (Stage E, 2026-05-16) is the PM's explicit
    must-produce list (task.output_paths). When provided, every entry
    is verified to exist on disk before emit_output succeeds — the
    payload field-name whitelist is no longer the sole defence.
    """
    schema = output_schema or {}
    root = project_root or ""
    expected = tuple(expected_paths or ())

    class _Bound(EmitOutput):
        _bound_task_id: ClassVar[str] = task_id
        _bound_schema: ClassVar[dict] = schema
        _bound_root: ClassVar[str] = root
        _bound_expected_paths: ClassVar[tuple[str, ...]] = expected

    return _Bound()


__all__ = ["EmitOutput", "make_emit_output_tool"]
