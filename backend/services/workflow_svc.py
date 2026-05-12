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
from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
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
        """Execute a task via its bound Agent.

        Prefers a real CrewAI Agent/Crew/Task pipeline (with tools + memory
        plumbing) when the agent has tools or the agent record requests it.
        Falls back to a direct LLM completion when CrewAI fails to start
        (e.g. litellm provider mismatch), so a missing tool config never
        blocks task execution.
        """
        agent = await crud.get_by_id("agents", task_input.agent_id)
        if not agent:
            raise ValueError(f"Agent {task_input.agent_id} not found")

        provider_id, model_name = await self._resolve_agent_llm(agent)

        # Try CrewAI first
        try:
            from services.crewai_runner import run_task_with_crewai
            text = await run_task_with_crewai(
                agent_row=agent,
                task_input=task_input,
                provider_id=provider_id,
                model_name=model_name,
            )
            log.info("workflow.agent_executed_via_crewai",
                     project_id=project_id, task_id=task_id,
                     agent_id=task_input.agent_id)
            return text
        except Exception as exc:
            log.warning("workflow.crewai_failed_falling_back",
                        project_id=project_id, task_id=task_id, error=str(exc))

        # Fallback: direct LLM call (legacy path; loses tool support)
        return await self._run_agent_direct_llm(
            project_id, task_id, task_input, agent, provider_id, model_name,
        )

    async def _run_agent_direct_llm(
        self,
        project_id: str,
        task_id: str,
        task_input: Any,
        agent: dict,
        provider_id: str,
        model_name: str,
    ) -> str:
        """Direct-LLM fallback when CrewAI can't be used (legacy behaviour)."""
        system_prompt = (
            f"你是一个 AI Agent。\n"
            f"角色: {agent.get('role', 'Assistant')}\n"
            f"目标: {agent.get('goal', '完成分配的任务')}\n"
            f"背景: {agent.get('backstory', '')}\n\n"
            f"请根据任务要求完成工作，输出详细的结果。"
        )

        task_prompt = f"## 任务: {task_input.title}\n\n{task_input.detail}\n"
        if task_input.upstream_outputs:
            task_prompt += "\n## 上游任务输出（供参考）:\n"
            for upstream_id, output in task_input.upstream_outputs.items():
                task_prompt += f"\n### 来自任务 {upstream_id}:\n"
                task_prompt += f"```json\n{json.dumps(output, ensure_ascii=False, indent=2)}\n```\n"

        if task_input.output_schema and task_input.output_schema != {}:
            task_prompt += (
                f"\n## 输出要求:\n"
                f"请确保你的输出能够被提取为以下 JSON Schema 格式:\n"
                f"```json\n{json.dumps(task_input.output_schema, ensure_ascii=False, indent=2)}\n```\n"
            )

        messages = [
            LlmMessage(role="system", content=system_prompt),
            LlmMessage(role="user", content=task_prompt),
        ]
        thinking_mode = bool(agent.get("thinking_mode", 0))

        response = await llm_gateway.chat(
            provider_id, model_name, messages,
            thinking_mode=thinking_mode,
        )
        log.info("workflow.agent_executed_via_llm",
                 project_id=project_id, task_id=task_id,
                 agent_id=task_input.agent_id,
                 tokens=response.usage.total_tokens)
        return response.text

    async def _extract_structured_output(self, project_id: str, task_id: str,
                                          raw_text: str,
                                          schema: dict) -> dict:
        """Use the task's agent LLM to extract structured output from raw text.

        First tries direct JSON parsing. If that fails, calls LLM with JSON mode
        to extract structured data matching the schema.
        """
        # Try direct JSON parse first
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        # Try extracting JSON block from markdown
        import re
        match = re.search(r"```json\s*\n(.*?)\n```", raw_text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass

        # Fall back to LLM extraction
        task = await crud.get_by_id("tasks", task_id)
        agent_id = task.get("agent_id", "") if task else ""
        agent = await crud.get_by_id("agents", agent_id) if agent_id else None

        provider_id, model_name = await self._resolve_agent_llm(agent)

        extraction_prompt = (
            "从以下文本中提取结构化数据，严格按照给定的 JSON Schema 输出纯 JSON（不要包含 markdown 代码块标记）。\n\n"
            f"## 目标 Schema:\n```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## 原始文本:\n{raw_text}\n\n"
            "请输出纯 JSON:"
        )

        messages = [
            LlmMessage(role="system", content="你是一个数据提取助手。只输出纯 JSON，不要任何其他文字。"),
            LlmMessage(role="user", content=extraction_prompt),
        ]

        try:
            response = await llm_gateway.chat(
                provider_id, model_name, messages,
                json_mode=True,
                temperature=0.1,
            )
            extracted = json.loads(response.text)
            if isinstance(extracted, dict):
                return extracted
        except (json.JSONDecodeError, TypeError, Exception) as exc:
            log.warning("workflow.extraction_failed",
                        task_id=task_id, error=str(exc))

        # Last resort: wrap raw text
        return {"_raw": raw_text}

    async def _resolve_agent_llm(self, agent: dict | None) -> tuple[str, str]:
        """Resolve an agent's LLM to (provider_id, model_name).

        Falls back to default_agent_model from app_settings.
        """
        if agent and agent.get("llm_id"):
            llm_id = agent["llm_id"]
            if ":" in llm_id:
                parts = llm_id.split(":", 1)
                return parts[0], parts[1]
            # Just provider_id
            models = await crud.get_all("llm_models", "provider_id = ?", (llm_id,))
            if models:
                return llm_id, models[0]["model_name"]

        # Fall back to default agent model
        row = await crud.get_all("app_settings", "key = ?", ("default_agent_model",))
        if row and row[0].get("value"):
            val = row[0]["value"]
            if ":" in val:
                parts = val.split(":", 1)
                return parts[0], parts[1]

        # Last fallback: any available provider
        providers = await crud.get_all("llm_providers")
        if providers:
            provider = providers[0]
            models = await crud.get_all("llm_models",
                                         "provider_id = ?", (provider["id"],))
            if models:
                return provider["id"], models[0]["model_name"]

        raise ValueError("未配置任何 LLM，无法执行 Agent 任务")

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
