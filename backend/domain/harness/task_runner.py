"""Task execution orchestration — assembles inputs, validates outputs, drives retries."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from domain.harness.states import TaskState


@dataclass
class TaskInput:
    task_id: str
    title: str
    detail: str
    agent_id: str
    output_schema: dict
    upstream_outputs: dict[str, Any]
    kind: str = "regular"
    # Stage E (2026-05-16): PM's must-produce file list, decoupled from
    # the output_schema's free-form field names. Empty list = "no files
    # expected"; None = legacy task with no contract (skip the check).
    output_paths: list[str] | None = None


@dataclass
class TaskOutput:
    task_id: str
    raw_text: str
    structured: dict | None = None
    validation_errors: list[str] | None = None

    @property
    def is_valid(self) -> bool:
        return self.structured is not None and not self.validation_errors


class TaskRunner:
    """Pure logic for preparing task execution and processing results.

    No IO — actual Agent execution and LLM extraction are delegated
    to workflow_svc via callbacks.
    """

    def __init__(self, tasks: list[dict]) -> None:
        self._tasks = {t["id"]: dict(t) for t in tasks}

    def prepare_input(self, task_id: str, completed_outputs: dict[str, dict]) -> TaskInput:
        task = self._tasks[task_id]
        deps = task.get("deps", [])

        upstream = {}
        for dep_id in deps:
            if dep_id in completed_outputs:
                upstream[dep_id] = completed_outputs[dep_id]

        output_schema = task.get("output_schema", {})
        if isinstance(output_schema, str):
            try:
                output_schema = json.loads(output_schema)
            except (json.JSONDecodeError, TypeError):
                output_schema = {}

        # output_paths is stored as a JSON string when present; null
        # means "no PM contract on file list" (legacy / iterate tasks).
        raw_paths = task.get("output_paths")
        output_paths: list[str] | None
        if raw_paths is None:
            output_paths = None
        elif isinstance(raw_paths, str):
            try:
                parsed = json.loads(raw_paths)
                output_paths = (
                    [p for p in parsed if isinstance(p, str)]
                    if isinstance(parsed, list)
                    else None
                )
            except (json.JSONDecodeError, TypeError):
                output_paths = None
        elif isinstance(raw_paths, list):
            output_paths = [p for p in raw_paths if isinstance(p, str)]
        else:
            output_paths = None

        return TaskInput(
            task_id=task_id,
            title=task.get("title", ""),
            detail=task.get("detail", ""),
            agent_id=task.get("agent_id", ""),
            output_schema=output_schema,
            upstream_outputs=upstream,
            kind=task.get("kind", "regular"),
            output_paths=output_paths,
        )

    def process_output(self, task_id: str, raw_text: str,
                       extracted_json: dict | None,
                       validation_errors: list[str] | None) -> TaskOutput:
        task = self._tasks[task_id]
        output_schema = task.get("output_schema", {})
        if isinstance(output_schema, str):
            try:
                output_schema = json.loads(output_schema)
            except (json.JSONDecodeError, TypeError):
                output_schema = {}

        is_free_text = not output_schema or output_schema == {}

        if is_free_text:
            return TaskOutput(
                task_id=task_id,
                raw_text=raw_text,
                structured={"_raw": raw_text},
            )

        if validation_errors:
            return TaskOutput(
                task_id=task_id,
                raw_text=raw_text,
                structured=None,
                validation_errors=validation_errors,
            )

        return TaskOutput(
            task_id=task_id,
            raw_text=raw_text,
            structured=extracted_json,
        )

    def should_retry(self, task_id: str, attempt: int) -> bool:
        task = self._tasks[task_id]
        max_retry = 3
        agent_id = task.get("agent_id")
        if agent_id:
            max_retry = task.get("max_retry", 3)
        return attempt < max_retry

    def get_execution_order(self) -> list[list[str]]:
        """Return tasks grouped by execution wave (parallel within wave)."""
        remaining = set(self._tasks.keys())
        done: set[str] = set()
        waves: list[list[str]] = []

        while remaining:
            wave = []
            for tid in list(remaining):
                task = self._tasks[tid]
                deps = set(task.get("deps", []))
                if deps.issubset(done):
                    wave.append(tid)
            if not wave:
                break
            waves.append(wave)
            done.update(wave)
            remaining -= set(wave)

        return waves
