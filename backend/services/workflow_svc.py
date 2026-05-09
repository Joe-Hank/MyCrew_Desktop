"""Workflow service — start/pause/resume Harness; state changes persisted each step."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from domain.harness.states import ProjectState, TaskState
from domain.harness.state_machine import HarnessStateMachine
from domain.harness.task_runner import TaskRunner, TaskOutput
from domain.qa.dag_validator import validate_dag
from domain.qa.output_validator import validate_output_schema
from domain.events import DomainEvent
from infra.repo import crud
from infra.event_bus.in_memory_bus import event_bus

log = structlog.get_logger()


class WorkflowService:
    def __init__(self) -> None:
        self._active: dict[str, HarnessStateMachine] = {}
        self._runners: dict[str, TaskRunner] = {}
        self._run_tasks: dict[str, asyncio.Task] = {}
        self._outputs: dict[str, dict[str, dict]] = {}

    # ── Public API ────────────────────────────────────────

    async def start(self, project_id: str) -> None:
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(f"Project {project_id} not found")

        tasks = await self._load_tasks(project_id)
        if not tasks:
            raise ValueError(f"Project {project_id} has no tasks")

        dag_errors = validate_dag(tasks)
        if dag_errors:
            error_msgs = [e.message for e in dag_errors]
            raise ValueError(f"DAG validation failed: {'; '.join(error_msgs)}")

        harness = HarnessStateMachine(
            project_id=project_id,
            state=ProjectState(project.get("state", "ready")),
            tasks=tasks,
        )
        runner = TaskRunner(tasks)

        events = harness.start()

        self._active[project_id] = harness
        self._runners[project_id] = runner
        self._outputs[project_id] = {}

        await self._persist_project_state(project_id, harness)
        await self._persist_all_task_states(project_id, harness)
        await event_bus.publish_all(events)

        self._schedule_ready_tasks(project_id, harness, runner)

        log.info("workflow.started", project_id=project_id)

    async def pause(self, project_id: str) -> None:
        harness = self._get_harness(project_id)
        events = harness.pause()

        await self._persist_project_state(project_id, harness)
        await self._persist_all_task_states(project_id, harness)
        await event_bus.publish_all(events)

        log.info("workflow.paused", project_id=project_id)

    async def resume(self, project_id: str) -> None:
        harness = self._get_harness(project_id)
        events = harness.resume()

        await self._persist_project_state(project_id, harness)
        await self._persist_all_task_states(project_id, harness)
        await event_bus.publish_all(events)

        runner = self._runners[project_id]
        self._schedule_ready_tasks(project_id, harness, runner)

        log.info("workflow.resumed", project_id=project_id)

    async def abort(self, project_id: str, reason: str = "") -> None:
        harness = self._get_harness(project_id)
        events = harness.abort(reason)

        await self._persist_project_state(project_id, harness)
        await self._persist_all_task_states(project_id, harness)
        await event_bus.publish_all(events)

        self._cleanup_project(project_id)
        log.info("workflow.aborted", project_id=project_id, reason=reason)

    async def retry_task(self, project_id: str, task_id: str) -> None:
        harness = self._get_harness(project_id)
        runner = self._runners[project_id]

        events = harness.retry_task(task_id)
        await self._persist_task_state(project_id, task_id, harness)
        await event_bus.publish_all(events)

        self._schedule_task(project_id, task_id, harness, runner)

    async def recover(self) -> list[str]:
        rows = await crud.get_all("projects", "state = ?", (ProjectState.RUNNING,))
        recovered = []
        for row in rows:
            try:
                await self.start(row["id"])
                recovered.append(row["id"])
            except Exception as exc:
                log.error("workflow.recover_failed",
                          project_id=row["id"], error=str(exc))
        return recovered

    async def pause_all(self) -> int:
        count = 0
        for project_id in list(self._active.keys()):
            try:
                await self.pause(project_id)
                count += 1
            except Exception:
                pass
        return count

    def get_active_projects(self) -> list[str]:
        return list(self._active.keys())

    # ── Task execution ────────────────────────────────────

    def _schedule_ready_tasks(self, project_id: str,
                               harness: HarnessStateMachine,
                               runner: TaskRunner) -> None:
        for task in harness.get_running_tasks():
            self._schedule_task(project_id, task["id"], harness, runner)

    def _schedule_task(self, project_id: str, task_id: str,
                        harness: HarnessStateMachine,
                        runner: TaskRunner) -> None:
        key = f"{project_id}:{task_id}"
        if key in self._run_tasks:
            return
        coro = self._execute_task(project_id, task_id, harness, runner)
        self._run_tasks[key] = asyncio.create_task(coro)

    async def _execute_task(self, project_id: str, task_id: str,
                             harness: HarnessStateMachine,
                             runner: TaskRunner) -> None:
        key = f"{project_id}:{task_id}"
        try:
            completed_outputs = self._outputs.get(project_id, {})
            task_input = runner.prepare_input(task_id, completed_outputs)

            raw_text = await self._run_agent(project_id, task_id, task_input)

            if task_input.output_schema and task_input.output_schema != {}:
                extracted = await self._extract_structured_output(
                    project_id, task_id, raw_text, task_input.output_schema
                )
                errors = validate_output_schema(extracted, task_input.output_schema)
            else:
                extracted = {"_raw": raw_text}
                errors = []

            output = runner.process_output(task_id, raw_text, extracted, errors)

            if output.is_valid:
                if project_id not in self._outputs:
                    self._outputs[project_id] = {}
                self._outputs[project_id][task_id] = output.structured

                await self._save_task_output(project_id, task_id, output)
                events = harness.complete_task(task_id)
            else:
                events = harness.validation_fail_task(task_id, output.validation_errors or [])

            await self._persist_task_state(project_id, task_id, harness)
            await self._persist_project_state(project_id, harness)
            await event_bus.publish_all(events)

            self._schedule_ready_tasks(project_id, harness, runner)

        except Exception as exc:
            log.error("workflow.task_failed",
                      project_id=project_id, task_id=task_id, error=str(exc))
            events = harness.fail_task(task_id, str(exc))
            await self._persist_task_state(project_id, task_id, harness)
            await self._persist_project_state(project_id, harness)
            await event_bus.publish_all(events)
        finally:
            self._run_tasks.pop(key, None)

    async def _run_agent(self, project_id: str, task_id: str,
                          task_input: Any) -> str:
        # Phase 5+ will wire CrewAI Agent execution here.
        # For now, return a placeholder indicating the task ran.
        log.info("workflow.agent_run_placeholder",
                 project_id=project_id, task_id=task_id,
                 agent_id=task_input.agent_id)
        return f"[Agent {task_input.agent_id} output for task {task_id}]"

    async def _extract_structured_output(self, project_id: str, task_id: str,
                                          raw_text: str,
                                          schema: dict) -> dict:
        # Phase 5+ will call the Task's bound LLM for structured extraction.
        # For now, attempt to parse raw_text as JSON directly.
        try:
            return json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            return {"_raw": raw_text}

    # ── Persistence ───────────────────────────────────────

    async def _load_tasks(self, project_id: str) -> list[dict]:
        rows = await crud.get_all("tasks", "project_id = ?", (project_id,))
        result = []
        for r in rows:
            t = dict(r)
            for field in ("deps", "output_schema"):
                if field in t and isinstance(t[field], str):
                    try:
                        t[field] = json.loads(t[field])
                    except (json.JSONDecodeError, TypeError):
                        t[field] = [] if field == "deps" else {}
            result.append(t)
        return result

    async def _persist_project_state(self, project_id: str,
                                      harness: HarnessStateMachine) -> None:
        await crud.update_by_id("projects", project_id, {
            "state": harness.state,
            "is_running": 1 if harness.state == ProjectState.RUNNING else 0,
            "progress_pct": harness.progress_pct,
        })

    async def _persist_task_state(self, project_id: str, task_id: str,
                                   harness: HarnessStateMachine) -> None:
        task = harness.get_task(task_id)
        updates: dict[str, Any] = {"status": task["status"]}
        if task["status"] == TaskState.RUNNING and not task.get("started_at"):
            from datetime import datetime, timezone
            updates["started_at"] = datetime.now(timezone.utc).isoformat()
        if task["status"] in (TaskState.DONE, TaskState.FAILED, TaskState.ABORTED):
            from datetime import datetime, timezone
            updates["finished_at"] = datetime.now(timezone.utc).isoformat()
        await crud.update_by_id("tasks", task_id, updates)

    async def _persist_all_task_states(self, project_id: str,
                                        harness: HarnessStateMachine) -> None:
        for task in harness.get_all_tasks():
            await self._persist_task_state(project_id, task["id"], harness)

    async def _save_task_output(self, project_id: str, task_id: str,
                                 output: TaskOutput) -> None:
        from bootstrap.paths import OUTPUT_DIR
        task_dir = OUTPUT_DIR / project_id / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        (task_dir / "out.json").write_text(
            json.dumps(output.structured, ensure_ascii=False, indent=2), encoding="utf-8")
        (task_dir / "out.md").write_text(output.raw_text, encoding="utf-8")

        await crud.update_by_id("tasks", task_id, {
            "io_out_ref": str(task_dir / "out.json"),
        })

    # ── Helpers ───────────────────────────────────────────

    def _get_harness(self, project_id: str) -> HarnessStateMachine:
        harness = self._active.get(project_id)
        if not harness:
            raise KeyError(f"Project {project_id} not active")
        return harness

    def _cleanup_project(self, project_id: str) -> None:
        self._active.pop(project_id, None)
        self._runners.pop(project_id, None)
        self._outputs.pop(project_id, None)
        for key in [k for k in self._run_tasks if k.startswith(f"{project_id}:")]:
            task = self._run_tasks.pop(key, None)
            if task:
                task.cancel()


workflow_svc = WorkflowService()
