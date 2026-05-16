"""Workflow service — start/pause/resume Harness; state changes persisted each step."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from domain.harness.states import ProjectState, TaskState
from domain.harness.state_machine import HarnessStateMachine
from domain.harness.task_runner import TaskRunner, TaskInput, TaskOutput
from domain.qa.dag_validator import validate_dag
from domain.qa.output_validator import validate_output_schema
from domain.events import DomainEvent
from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud
from infra.event_bus.in_memory_bus import event_bus

log = structlog.get_logger()


# ── Failure classification ─────────────────────────────────────────
# Heuristics on the exception string. Generic but enough to give the
# user a one-word hint on hover instead of just "执行失败".
# Order matters — most specific patterns first.
_ERROR_KIND_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("quota", (
        "rate_limit", "rate limit", "ratelimit", "quota", "insufficient_quota",
        "billing", "exceeded your current quota", "tokens_exhausted",
        "402", "payment required", "余额不足", "额度",
    )),
    ("auth", (
        "401", "unauthorized", "invalid api key", "incorrect api key",
        "authentication", "auth_failed",
    )),
    ("mcp", (
        "mcp", "connection refused", "no mcp", "tool not found",
        "tool_not_registered", "unity bridge", "blender mcp", "comfyui mcp",
        "8090", "127.0.0.1:8090",
    )),
    ("network", (
        "timeout", "timed out", "connection reset", "connection error",
        "dns", "getaddrinfo", "name resolution", "ssl", "503", "504",
        "bad gateway", "service unavailable", "ECONNRESET", "ECONNREFUSED",
    )),
    ("stalled", (
        "stalled:", "no activity past timeout", "watchdog",
    )),
    ("tool", (
        "tool_invocation_failed", "tool execution failed", "guarded",
        "permission_denied", "denied", "tool error",
    )),
]


def _extract_output_paths(output_schema: dict, _detail: str = "") -> list[str]:
    """Best-effort recovery of the PM contract's output_paths list.

    PM v3/v4 stores the expected file paths inside output_schema under
    `properties.file_paths.const` or `properties.file_paths.examples`,
    and sometimes also lists them in plain text inside task.detail.
    The Crew runner pipes this into every step's prompt so Head/Executor
    agents see exactly what they're contractually obliged to produce.

    Returns [] if nothing concrete is found — downstream steps still get
    the raw output_schema as a fallback.
    """
    paths: list[str] = []
    if isinstance(output_schema, dict):
        props = output_schema.get("properties") or {}
        for key in ("file_paths", "output_paths", "paths"):
            entry = props.get(key) or {}
            if isinstance(entry, dict):
                for candidate_key in ("const", "default", "examples"):
                    val = entry.get(candidate_key)
                    if isinstance(val, list):
                        paths.extend(p for p in val if isinstance(p, str) and p.strip())
                    elif isinstance(val, str) and val.strip():
                        paths.append(val.strip())
        # Sometimes the contract is at top level
        top_val = output_schema.get("required_paths")
        if isinstance(top_val, list):
            paths.extend(p for p in top_val if isinstance(p, str))
    # Dedup while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def _classify_task_error(err: str) -> str:
    """Return a short kind label so the frontend can render a specific
    Chinese hint on hover instead of just \"执行失败\".

    Falls back to \"unknown\" if no pattern matched."""
    if not err:
        return "unknown"
    lower = err.lower()
    for kind, patterns in _ERROR_KIND_PATTERNS:
        for p in patterns:
            if p.lower() in lower:
                return kind
    return "unknown"


class WorkflowService:
    def __init__(self) -> None:
        self._active: dict[str, HarnessStateMachine] = {}
        self._runners: dict[str, TaskRunner] = {}
        self._run_tasks: dict[str, asyncio.Task] = {}
        self._outputs: dict[str, dict[str, dict]] = {}
        # Per-project asyncio.Lock — serialises start/pause/resume/abort/retry
        # for the same project so a double-click Start or a concurrent
        # retry can't produce two harnesses or duplicate asyncio.Tasks.
        # Lazily created in _get_project_lock(); the lock map itself is
        # mutated only on the main event loop (FastAPI request handlers),
        # so dict mutation is single-threaded.
        # Audit (2026-05-16 architecture-audit.md, Top 5 #3) called out
        # the TOCTOU race here as P1; this is the fix.
        self._project_locks: dict[str, asyncio.Lock] = {}

    def _get_project_lock(self, project_id: str) -> asyncio.Lock:
        lock = self._project_locks.get(project_id)
        if lock is None:
            lock = asyncio.Lock()
            self._project_locks[project_id] = lock
        return lock

    # ── Public API ────────────────────────────────────────
    # Every state-mutating entry point grabs the per-project lock first
    # so start/pause/resume/abort/retry_task on the same project_id are
    # serialised. Concurrent requests on DIFFERENT projects still run
    # in parallel.

    async def start(self, project_id: str) -> None:
        async with self._get_project_lock(project_id):
            await self._start_locked(project_id)

    async def _start_locked(self, project_id: str) -> None:
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(f"Project {project_id} not found")

        tasks = await self._load_tasks(project_id)
        if not tasks:
            raise ValueError(f"Project {project_id} has no tasks")

        # Reject projects where any task has no executable performer
        # bound. PM v4 tasks bind via performer_kind + performer_id;
        # legacy / setup / iterate tasks still use the agent_id column
        # alone (workflow_svc._run_agent falls back to it when
        # performer_kind is null). A task is "assignable" when at least
        # one of those two channels names a real id — anything else means
        # Phase 5 didn't pick anyone and we'd crash on dispatch.
        #
        # Wire-level guarantee: every code path that calls start() —
        # frontend pre-check, retry flows, scheduler — gets the same rule.
        def _has_performer(t: dict) -> bool:
            kind = t.get("performer_kind")
            if kind == "crew" and t.get("performer_id"):
                return True
            # 'agent' kind OR legacy null kind: either column counts.
            return bool(t.get("agent_id") or t.get("performer_id"))

        missing_perf = [t for t in tasks if not _has_performer(t)]
        if missing_perf:
            titles = ", ".join(t.get("title", "未命名") for t in missing_perf)
            raise ValueError(
                f"以下任务未指定执行者（Agent/Crew），无法启动：{titles}",
            )

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
        async with self._get_project_lock(project_id):
            await self._pause_locked(project_id)

    async def _pause_locked(self, project_id: str) -> None:
        # Live-harness path — normal in-session pause
        harness = self._active.get(project_id)
        if harness is not None:
            events = harness.pause()
            await self._persist_project_state(project_id, harness)
            await self._persist_all_task_states(project_id, harness)
            await event_bus.publish_all(events)
            log.info("workflow.paused", project_id=project_id)
            return

        # Orphan path — project was running before backend restart, so
        # there's no harness in memory. Reconcile directly: stop scheduling,
        # flip state to paused. Without this fallback the pause button
        # silently 404s on any project that survived a backend restart.
        from infra.repo import crud
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(project_id)
        # Mark any still-running task rows as paused so the UI matches
        running_tasks = await crud.get_all(
            "tasks", "project_id = ? AND status = ?", (project_id, "running"),
        )
        for t in running_tasks:
            await crud.update_by_id("tasks", t["id"], {"status": "paused"})
        await crud.update_by_id("projects", project_id, {
            "state": "paused",
            "is_running": 0,
        })
        log.info("workflow.paused_orphan",
                 project_id=project_id, tasks_flipped=len(running_tasks))

    async def resume(self, project_id: str) -> None:
        async with self._get_project_lock(project_id):
            await self._resume_locked(project_id)

    async def _resume_locked(self, project_id: str) -> None:
        harness = self._get_harness(project_id)
        events = harness.resume()

        await self._persist_project_state(project_id, harness)
        await self._persist_all_task_states(project_id, harness)
        await event_bus.publish_all(events)

        runner = self._runners[project_id]
        self._schedule_ready_tasks(project_id, harness, runner)

        log.info("workflow.resumed", project_id=project_id)

    async def abort(self, project_id: str, reason: str = "") -> None:
        async with self._get_project_lock(project_id):
            await self._abort_locked(project_id, reason)

    async def _abort_locked(self, project_id: str, reason: str = "") -> None:
        # Live-harness path
        harness = self._active.get(project_id)
        if harness is not None:
            events = harness.abort(reason)
            await self._persist_project_state(project_id, harness)
            await self._persist_all_task_states(project_id, harness)
            await event_bus.publish_all(events)
            self._cleanup_project(project_id)
            log.info("workflow.aborted",
                     project_id=project_id, reason=reason)
            return

        # Orphan path — same idea as pause(): user wants to give up on a
        # project that survived a backend restart. Without this fallback
        # the abort button 404s and the project stays "stuck" forever.
        from infra.repo import crud
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(project_id)
        non_terminal = await crud.get_all(
            "tasks",
            "project_id = ? AND status NOT IN ('done','failed','aborted','validation_failed')",
            (project_id,),
        )
        for t in non_terminal:
            await crud.update_by_id("tasks", t["id"], {"status": "aborted"})
        await crud.update_by_id("projects", project_id, {
            "state": "aborted",
            "is_running": 0,
        })
        log.info("workflow.aborted_orphan",
                 project_id=project_id, tasks_aborted=len(non_terminal),
                 reason=reason)

    async def retry_task(
        self,
        project_id: str,
        task_id: str,
        cleanup_artifacts: bool = True,
    ) -> None:
        """Re-run a failed task.

        ``cleanup_artifacts`` (Stage B, 2026-05-16): when true (the
        default), wipe ``<OUTPUT_DIR>/<pid>/<tid>/{sub,out.json,out.md}``
        before re-scheduling. Without cleanup, the previous run's residue
        can pass emit_output's path-existence check (the agent claims new
        paths that *happen* to still be on disk) — that's the stale-state
        trap Stage B is built to close. Users who set this false from the
        confirm dialog explicitly opt into "keep the residue and rerun
        anyway" — useful when the previous emit_output was correct but a
        downstream step failed.

        Auto-resume: if the project's harness was lost (backend restart
        after the original failure, project state `stalled` / `failed`),
        we rebuild it from the DB instead of 404-ing. Previously a user
        hitting Retry after a restart silently saw nothing happen because
        the route raised KeyError("Project not active").
        """
        async with self._get_project_lock(project_id):
            await self._ensure_active(project_id)
            harness = self._get_harness(project_id)
            runner = self._runners[project_id]

            if cleanup_artifacts:
                await self._cleanup_task_artifacts(project_id, task_id)

            events = harness.retry_task(task_id)
            await self._persist_task_state(project_id, task_id, harness)
            await event_bus.publish_all(events)

            self._schedule_task(project_id, task_id, harness, runner)

    async def _ensure_active(self, project_id: str) -> None:
        """Make sure `_active[project_id]` is populated; rebuild from DB
        if not. Idempotent — already-active projects are a no-op.

        Preserves on-disk task statuses (done / failed / etc) so the
        rebuilt harness reflects reality, not a fresh start. We avoid
        calling harness.start() here because that would broadcast
        ProjectStarted and try to activate ready tasks; the caller
        (retry_task, manual rerun, etc.) drives what gets scheduled.
        """
        if project_id in self._active:
            return
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(f"Project {project_id} not found")
        tasks = await self._load_tasks(project_id)
        if not tasks:
            raise ValueError(f"Project {project_id} has no tasks")

        # Build harness in whatever state the project is currently in.
        # If it was 'stalled' or 'failed', we flip to RUNNING below so
        # the scheduler can fire — caller has decided this project is
        # active again by virtue of asking to retry a task.
        harness = HarnessStateMachine(
            project_id=project_id,
            state=ProjectState(project.get("state", "ready")),
            tasks=tasks,
        )
        runner = TaskRunner(tasks)

        # Rehydrate completed task outputs so downstream retries can
        # find their upstream context (TaskInput.upstream_outputs).
        outputs: dict[str, dict] = {}
        from bootstrap.paths import OUTPUT_DIR
        for t in tasks:
            if t.get("status") != "done":
                continue
            out_path = OUTPUT_DIR / project_id / t["id"] / "out.json"
            if not out_path.exists():
                continue
            try:
                outputs[t["id"]] = json.loads(out_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

        # Flip project to RUNNING if it wasn't already — this is the
        # implicit "resume" that gets us out of stalled/failed terminal-
        # looking states without forcing the user to click Start.
        if harness.state != ProjectState.RUNNING:
            harness._transition_project(ProjectState.RUNNING)
            await crud.update_by_id("projects", project_id, {
                "state": "running",
                "is_running": 1,
            })

        self._active[project_id] = harness
        self._runners[project_id] = runner
        self._outputs[project_id] = outputs
        log.info("workflow.auto_resumed_for_retry",
                 project_id=project_id,
                 rehydrated_outputs=len(outputs))

    async def _cleanup_task_artifacts(
        self, project_id: str, task_id: str,
    ) -> None:
        """Remove a task's previous outputs so the next run starts clean.

        Wipes the per-task output dir's ``sub/`` directory plus the
        top-level ``out.json`` / ``out.md`` ; leaves ``in.md`` / ``in.json``
        intact because those describe the *task itself* (PM contract +
        upstream context), not the previous run's outputs. The task row's
        ``io_out_ref`` column is cleared in the same pass so the IO viewer
        doesn't display a path that no longer exists.
        """
        import shutil
        from bootstrap.paths import OUTPUT_DIR

        task_dir = OUTPUT_DIR / project_id / task_id
        removed: list[str] = []
        sub_dir = task_dir / "sub"
        if sub_dir.exists():
            try:
                shutil.rmtree(sub_dir)
                removed.append("sub/")
            except OSError as exc:
                log.warning("retry.cleanup_sub_failed",
                            task_id=task_id, error=str(exc))
        for name in ("out.json", "out.md"):
            f = task_dir / name
            if f.exists():
                try:
                    f.unlink()
                    removed.append(name)
                except OSError as exc:
                    log.warning("retry.cleanup_file_failed",
                                task_id=task_id, file=name, error=str(exc))

        # Clear the DB pointer so the IO viewer doesn't tease a stale file.
        try:
            await crud.update_by_id("tasks", task_id, {"io_out_ref": None})
        except Exception as exc:  # noqa: BLE001
            log.warning("retry.cleanup_db_clear_failed",
                        task_id=task_id, error=str(exc))

        log.info("retry.artifacts_cleaned",
                 task_id=task_id, removed=removed or ["(nothing)"])

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

            # Debugger short-circuit: when final_qa already reported
            # verdict="pass" there's nothing to debug, so we skip the
            # LLM call entirely and mark the task done with a
            # synthesised summary. Saves a Crew-budget round of tokens
            # on every clean project. Implemented here (not in
            # prepare_input) so the IO viewer still has a real in.md.
            if task_input.kind == "debugger":
                fast_path = await self._maybe_skip_debugger(task_input)
                if fast_path is not None:
                    if project_id not in self._outputs:
                        self._outputs[project_id] = {}
                    self._outputs[project_id][task_id] = fast_path
                    await self._save_task_input(project_id, task_id, task_input)
                    await self._save_task_output(
                        project_id, task_id,
                        TaskOutput(task_id=task_id, raw_text="",
                                   structured=fast_path),
                    )
                    await crud.update_by_id("tasks", task_id, {
                        "validation_errors": None,
                        "last_error": None,
                        "last_error_kind": None,
                    })
                    events = harness.complete_task(task_id)
                    await self._persist_task_state(project_id, task_id, harness)
                    await self._persist_project_state(project_id, harness)
                    await event_bus.publish_all(events)
                    self._schedule_ready_tasks(project_id, harness, runner)
                    return

            # Persist the prepared input next to the future output so the
            # IO viewer / agent guidance chat can read what the task was
            # actually told to do (previously the input panel was always
            # blank because io_in_ref was never written).
            await self._save_task_input(project_id, task_id, task_input)

            raw_text = await self._run_agent(project_id, task_id, task_input)

            # Prefer emit_output's captured payload if the agent called it.
            # When present, it has already been validated against the
            # task's output_schema inside the tool, so we skip the
            # text-extraction fallback entirely.
            from src.tools.builtin.local._output_capture import pop_output
            captured = pop_output(task_id)
            if captured is not None:
                extracted = captured if isinstance(captured, dict) else {"value": captured}
                errors = []
            elif task_input.output_schema and task_input.output_schema != {}:
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
                # Clear any stale validation_errors / last_error from a
                # prior failed run (retry path) so the UI doesn't show
                # old red noise.
                await crud.update_by_id("tasks", task_id, {
                    "validation_errors": None,
                    "last_error": None,
                    "last_error_kind": None,
                })
                events = harness.complete_task(task_id)
            else:
                # Persist the error list so the UI / retry path / QA agent
                # can show *why* the task failed validation — previously
                # this info evaporated with the WS event.
                err_list = output.validation_errors or []
                await crud.update_by_id("tasks", task_id, {
                    "validation_errors": json.dumps(err_list, ensure_ascii=False),
                    "last_error": "; ".join(err_list)[:500] if err_list else None,
                    "last_error_kind": "validation",
                })
                events = harness.validation_fail_task(task_id, err_list)

            await self._persist_task_state(project_id, task_id, harness)
            await self._persist_project_state(project_id, harness)
            await event_bus.publish_all(events)

            self._schedule_ready_tasks(project_id, harness, runner)

        except Exception as exc:
            err_msg = str(exc)
            kind = _classify_task_error(err_msg)
            log.error("workflow.task_failed",
                      project_id=project_id, task_id=task_id,
                      error=err_msg, kind=kind)
            await crud.update_by_id("tasks", task_id, {
                "last_error": err_msg[:500],
                "last_error_kind": kind,
            })
            events = harness.fail_task(task_id, err_msg)
            await self._persist_task_state(project_id, task_id, harness)
            await self._persist_project_state(project_id, harness)
            await event_bus.publish_all(events)
        finally:
            self._run_tasks.pop(key, None)

    async def _maybe_skip_debugger(self, task_input: Any) -> dict | None:
        """Return a synthesised debugger output if final_qa already passed
        (so the LLM call can be skipped), or None if the debugger needs
        to actually run.

        The debugger task depends on final_qa (set up by
        create_workflow._normalize_tasks). We look at the final_qa
        output in the upstream_outputs the runner built — if its
        verdict is "pass", no issues exist to fix.
        """
        for dep_id, dep_output in (task_input.upstream_outputs or {}).items():
            if not isinstance(dep_output, dict):
                continue
            dep_row = await crud.get_by_id("tasks", dep_id)
            if not dep_row or dep_row.get("kind") != "final_qa":
                continue
            if dep_output.get("verdict") == "pass":
                return {
                    "verdict": "fixed",
                    "fixes_applied": [],
                    "issues_escalated": [],
                    "summary": (
                        "final_qa 报告 verdict=pass，没有 issue 需要修复；"
                        "Debugger 自动跳过 LLM 调用。"
                    ),
                }
            break
        return None

    async def _run_agent(self, project_id: str, task_id: str,
                          task_input: Any) -> str:
        """Execute a task — route to Crew runner or single-agent runner.

        PM v4 introduced a performer_kind column on tasks. When the task
        was assigned a Crew (`performer_kind == 'crew'`), the orchestrator
        walks the Crew's agent_sequence step-by-step. Otherwise (v3
        legacy or v4 single-agent picks) the original single-agent path
        runs unchanged.
        """
        task_row = await crud.get_by_id("tasks", task_id) or {}
        performer_kind = task_row.get("performer_kind")

        if performer_kind == "crew":
            performer_id = task_row.get("performer_id")
            if not performer_id:
                raise ValueError(
                    f"Task {task_id} has performer_kind='crew' but no performer_id"
                )
            return await self._run_crew(project_id, task_id, task_input, performer_id)

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
                project_id=project_id,
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

    async def _run_crew(self, project_id: str, task_id: str,
                         task_input: Any, crew_id: str) -> str:
        """Walk a Crew's agent_sequence head → executors → QA.

        Per Q1 / Q2: each step is its own single-agent kickoff; the
        previous step's emit_output payload is injected into the next
        step's description as structured JSON.

        Per Q7: a pause flag is checked at every step boundary; when set,
        the loop exits cleanly without touching the in-flight CrewAI
        worker (it has already completed the current step).

        Returns a Markdown summary of the full Crew run — workflow_svc's
        existing post-processing will pick up the QA step's structured
        emit_output via `pop_output(task_id)` (the QA step is bound to
        the parent task_id key so the chain's tail flows into the same
        downstream pipeline as a v3 single-agent task).
        """
        from bootstrap.paths import OUTPUT_DIR
        # Imported via this module so tests can monkey-patch it.
        from services import crewai_runner as _crewai_runner

        crew = await crud.get_by_id("crews", crew_id)
        if not crew:
            raise ValueError(f"Crew {crew_id} not found")
        sequence_raw = crew.get("agent_sequence") or "[]"
        try:
            sequence = json.loads(sequence_raw) if isinstance(sequence_raw, str) else sequence_raw
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"Crew {crew_id} has malformed agent_sequence: {exc}")
        if not isinstance(sequence, list) or not sequence:
            raise ValueError(f"Crew {crew_id} agent_sequence is empty")

        project = await crud.get_by_id("projects", project_id) or {}
        project_root = project.get("root_path") or None

        # output_paths is part of the PM contract; tasks table doesn't
        # have it as a column, but the upstream Plan Maker stores it
        # inside output_schema (as "required" list of path strings) OR
        # in detail. For now derive a best-effort list from output_schema.
        parent_output_schema = task_input.output_schema or {}
        parent_output_paths = _extract_output_paths(parent_output_schema, task_input.detail or "")

        sub_dir = OUTPUT_DIR / project_id / task_id / "sub"
        sub_dir.mkdir(parents=True, exist_ok=True)

        prev_payload: dict | None = None
        step_summaries: list[str] = []

        for i, step in enumerate(sequence):
            # Q7 soft pause: cooperative check at step boundary
            harness = self._active.get(project_id)
            if harness and harness.state == ProjectState.PAUSED:
                log.info("crew.paused_at_step_boundary",
                         task_id=task_id, step_index=i)
                step_summaries.append(f"⏸ Step {i + 1} skipped — project paused")
                break

            step_role = step.get("role") or "executor"
            agent_id = step.get("agent_id")
            step_instructions = step.get("step_instructions") or ""
            agent_row = await crud.get_by_id("agents", agent_id) if agent_id else None
            if not agent_row:
                raise ValueError(
                    f"Crew {crew_id} step {i} references missing agent_id {agent_id}"
                )
            provider_id, model_name = await self._resolve_agent_llm(agent_row)

            await self._broadcast_sub_step(
                project_id, task_id, i, step_role,
                agent_id, agent_row.get("role", ""), "started",
            )

            try:
                text, captured = await _crewai_runner.run_crew_step_with_crewai(
                    agent_row=agent_row,
                    step_role=step_role,
                    step_index=i,
                    step_instructions=step_instructions,
                    project_id=project_id,
                    project_root=project_root,
                    parent_task_id=task_id,
                    parent_task_title=task_input.title,
                    parent_task_detail=task_input.detail or "",
                    parent_output_schema=parent_output_schema,
                    parent_output_paths=parent_output_paths,
                    upstream_outputs=task_input.upstream_outputs or {},
                    prev_step_payload=prev_payload,
                    provider_id=provider_id,
                    model_name=model_name,
                )
            except Exception as exc:
                err = str(exc)
                log.error("crew.step_failed",
                          task_id=task_id, step_index=i, error=err)
                await self._broadcast_sub_step(
                    project_id, task_id, i, step_role,
                    agent_id, agent_row.get("role", ""), "failed",
                    error=err[:200],
                )
                raise

            # Persist sub-step IO
            await self._save_sub_step_io(
                project_id, task_id, i, step_role,
                step_instructions, prev_payload,
                text, captured,
            )

            prev_payload = captured  # may be None — next step sees null
            step_summaries.append(
                f"✓ Step {i + 1}/{len(sequence)} [{step_role}] {agent_row.get('role', '')} "
                f"— captured={'yes' if captured else 'no'}"
            )

            await self._broadcast_sub_step(
                project_id, task_id, i, step_role,
                agent_id, agent_row.get("role", ""), "completed",
            )

        # The QA step's emit_output was bound to parent task_id, so the
        # caller's `pop_output(task_id)` finds it. We return a markdown
        # log of the Crew run for the agent_output / debug viewers.
        return "\n".join(step_summaries) or "(empty Crew run)"

    async def _save_sub_step_io(self, project_id: str, task_id: str,
                                 step_index: int, step_role: str,
                                 step_instructions: str,
                                 prev_payload: dict | None,
                                 raw_text: str,
                                 captured: dict | None) -> None:
        """Write `<OUTPUT_DIR>/<pid>/<tid>/sub/<i>_<role>_{in,out}.json+md`.

        These files back the sub-card IO viewer in the frontend — every
        step gets its own observable slice.
        """
        from bootstrap.paths import OUTPUT_DIR
        sub_dir = OUTPUT_DIR / project_id / task_id / "sub"
        sub_dir.mkdir(parents=True, exist_ok=True)

        in_payload = {
            "step_index": step_index,
            "step_role": step_role,
            "step_instructions": step_instructions,
            "prev_step_payload": prev_payload,
        }
        (sub_dir / f"{step_index}_{step_role}_in.json").write_text(
            json.dumps(in_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        out_payload = {
            "step_index": step_index,
            "step_role": step_role,
            "raw_text": raw_text[:4000],
            "captured": captured,
        }
        (sub_dir / f"{step_index}_{step_role}_out.json").write_text(
            json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (sub_dir / f"{step_index}_{step_role}_out.md").write_text(
            f"# Step {step_index + 1} · {step_role}\n\n"
            f"## Raw text\n\n```\n{raw_text[:4000]}\n```\n\n"
            f"## Captured (emit_output)\n\n```json\n"
            f"{json.dumps(captured, ensure_ascii=False, indent=2) if captured else '(none)'}\n```",
            encoding="utf-8",
        )

    async def _broadcast_sub_step(
        self, project_id: str, task_id: str,
        step_index: int, step_role: str,
        agent_id: str | None, agent_role: str,
        status: str, error: str = "",
    ) -> None:
        """Fire a task.sub_step WS event so the Crew sub-cards update live."""
        try:
            from datetime import datetime, timezone
            from api.ws import manager
            payload = {
                "task_id": task_id,
                "project_id": project_id,
                "step_index": step_index,
                "role": step_role,
                "agent_id": agent_id or "",
                "agent_role": agent_role,
                "status": status,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            if error:
                payload["error"] = error
            await manager.broadcast("task.sub_step", payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("workflow.sub_step_broadcast_failed",
                        task_id=task_id, error=str(exc))

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
            now_iso = datetime.now(timezone.utc).isoformat()
            updates["started_at"] = now_iso
            # Seed last_activity_at so the watchdog has a baseline before
            # the first step callback fires.
            updates["last_activity_at"] = now_iso
        # All terminal states must stamp finished_at — previously
        # VALIDATION_FAILED was missing, so QA-failed projects looked
        # like they never wrapped up.
        if task["status"] in (
            TaskState.DONE, TaskState.FAILED, TaskState.ABORTED,
            TaskState.VALIDATION_FAILED,
        ):
            from datetime import datetime, timezone
            updates["finished_at"] = datetime.now(timezone.utc).isoformat()
        await crud.update_by_id("tasks", task_id, updates)

    async def _persist_all_task_states(self, project_id: str,
                                        harness: HarnessStateMachine) -> None:
        for task in harness.get_all_tasks():
            await self._persist_task_state(project_id, task["id"], harness)

    async def _save_task_input(self, project_id: str, task_id: str,
                                task_input: TaskInput) -> None:
        """Persist the prepared TaskInput so the IO viewer can show it.

        Mirrors _save_task_output: writes `<OUTPUT_DIR>/<pid>/<tid>/in.json`
        + `in.md` and stamps `tasks.io_in_ref` with the JSON path."""
        from bootstrap.paths import OUTPUT_DIR
        task_dir = OUTPUT_DIR / project_id / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "task_id": task_input.task_id,
            "title": task_input.title,
            "detail": task_input.detail,
            "agent_id": task_input.agent_id,
            "kind": task_input.kind,
            "output_schema": task_input.output_schema,
            "upstream_outputs": task_input.upstream_outputs,
        }
        (task_dir / "in.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # Human-readable markdown view of the task brief
        md_lines = [
            f"# Task: {task_input.title}",
            "",
            f"**task_id**: `{task_input.task_id}`  ",
            f"**agent_id**: `{task_input.agent_id}`  ",
            f"**kind**: `{task_input.kind}`",
            "",
            "## 详细指令",
            task_input.detail or "(none)",
            "",
            "## 期望输出 Schema",
            "```json",
            json.dumps(task_input.output_schema, ensure_ascii=False, indent=2),
            "```",
        ]
        if task_input.upstream_outputs:
            md_lines += [
                "",
                "## 上游输出",
                "```json",
                json.dumps(task_input.upstream_outputs, ensure_ascii=False, indent=2),
                "```",
            ]
        (task_dir / "in.md").write_text("\n".join(md_lines), encoding="utf-8")

        await crud.update_by_id("tasks", task_id, {
            "io_in_ref": str(task_dir / "in.json"),
        })

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
        # Drop the per-project lock too — a stale lock can't deadlock
        # anything (it's project-keyed and the project is now gone) but
        # keeping it around accumulates entries over a long-running
        # process. New start() will allocate a fresh one.
        self._project_locks.pop(project_id, None)

    # ── Project requirement queries ───────────────────────

    async def required_mcps(self, project_id: str) -> list[dict]:
        """Compute the MCP servers a project actually needs to run.

        Walks: project tasks → bound performer (agent or crew) →
        agent(s) → tool_ids → tool names → MCP servers whose
        discovered_tools cover those names.

        Returned shape per server:
          { server_id, name, status, tools_used: [...], missing_tools: [...] }
        `tools_used` are the tool names from this project that map to this
        MCP. `missing_tools` are tool names the project needs but the
        server can't currently provide (server disconnected, or the tool
        isn't in the server's discovered set — usually means it dropped
        between discovery and now).

        TaskHeader renders this list as a "required MCP" status row +
        uses it as a pre-flight gate on Start (blocks start if anything
        in the list is not connected).
        """
        tasks = await self._load_tasks(project_id)
        if not tasks:
            return []

        # Collect every agent_id this project touches (Crew members
        # included). Setup tasks bind agent_id directly; Crew tasks
        # bind via crews.agent_sequence[*].agent_id.
        agent_ids: set[str] = set()
        crew_ids: set[str] = set()
        for t in tasks:
            kind = t.get("performer_kind")
            pid = t.get("performer_id") or t.get("agent_id")
            if not pid:
                continue
            if kind == "crew":
                crew_ids.add(pid)
            else:
                agent_ids.add(pid)
        for crew_id in crew_ids:
            crew = await crud.get_by_id("crews", crew_id)
            if not crew:
                continue
            try:
                seq = json.loads(crew.get("agent_sequence") or "[]")
            except (json.JSONDecodeError, TypeError):
                continue
            for step in seq:
                aid = step.get("agent_id") if isinstance(step, dict) else None
                if aid:
                    agent_ids.add(aid)

        # Gather all tool_ids those agents reference.
        tool_ids: set[str] = set()
        for aid in agent_ids:
            agent = await crud.get_by_id("agents", aid)
            if not agent:
                continue
            try:
                ids = json.loads(agent.get("tool_ids") or "[]")
            except (json.JSONDecodeError, TypeError):
                continue
            tool_ids.update(t for t in ids if isinstance(t, str))

        # Resolve tool ids → tool names.
        tool_names: set[str] = set()
        for tid in tool_ids:
            row = await crud.get_by_id("tools", tid)
            if row and row.get("name"):
                tool_names.add(row["name"])

        # Walk MCP servers; a server is "required" if any of its
        # discovered_tools' names intersect our set. Pool status comes
        # from the live MCP pool (in-memory) — what we ACTUALLY have.
        from infra.mcp.pool import mcp_pool
        live_status: dict[str, str] = {
            s["server_id"]: s["status"]
            for s in mcp_pool.get_all_statuses()
        }

        servers = await crud.get_all("mcp_servers")
        required: list[dict] = []
        for s in servers:
            if not s.get("enabled"):
                continue
            try:
                discovered = json.loads(s.get("discovered_tools") or "[]")
            except (json.JSONDecodeError, TypeError):
                discovered = []
            offered = {
                d.get("name") for d in discovered
                if isinstance(d, dict) and d.get("name")
            }
            used = sorted(tool_names & offered)
            if not used:
                continue  # this server isn't relevant to the project
            required.append({
                "server_id": s["id"],
                "name": s["name"],
                "status": live_status.get(s["id"], "disconnected"),
                "tools_used": used,
                "missing_tools": [],  # reserved for future drift detection
            })
        return required


workflow_svc = WorkflowService()
