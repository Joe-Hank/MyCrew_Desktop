"""Pure project-level state machine — zero IO, all side effects via ports."""
from __future__ import annotations

from domain.harness.states import (
    ProjectState, TaskState, PROJECT_TRANSITIONS, TASK_TRANSITIONS,
    TERMINAL_TASK_STATES, FAILED_TASK_STATES,
)
from domain.events import (
    ProjectStarted, ProjectPaused, ProjectResumed, ProjectCompleted,
    ProjectAborted, ProjectProgress,
    TaskStarted, TaskCompleted, TaskFailed, TaskPaused, TaskBlocked,
    TaskValidationFailed, DomainEvent,
)


class InvalidTransition(Exception):
    pass


class HarnessStateMachine:
    """Drives project + task state transitions. Pure logic — no DB, no IO."""

    def __init__(self, project_id: str, state: ProjectState,
                 tasks: list[dict]) -> None:
        self.project_id = project_id
        self.state = state
        self._tasks = {t["id"]: dict(t) for t in tasks}

    # ── Project transitions ───────────────────────────────

    def start(self) -> list[DomainEvent]:
        self._transition_project(ProjectState.RUNNING)
        events: list[DomainEvent] = [ProjectStarted(project_id=self.project_id)]
        events.extend(self._activate_ready_tasks())
        return events

    def pause(self) -> list[DomainEvent]:
        self._transition_project(ProjectState.PAUSED)
        events: list[DomainEvent] = [ProjectPaused(project_id=self.project_id)]
        for t in self._tasks.values():
            if t["status"] == TaskState.PENDING:
                self._transition_task(t["id"], TaskState.PAUSED)
                events.append(TaskPaused(project_id=self.project_id, task_id=t["id"]))
        return events

    def resume(self) -> list[DomainEvent]:
        self._transition_project(ProjectState.RUNNING)
        events: list[DomainEvent] = [ProjectResumed(project_id=self.project_id)]
        for t in self._tasks.values():
            if t["status"] == TaskState.PAUSED:
                self._transition_task(t["id"], TaskState.PENDING)
        events.extend(self._activate_ready_tasks())
        return events

    def abort(self, reason: str = "") -> list[DomainEvent]:
        self._transition_project(ProjectState.ABORTED)
        events: list[DomainEvent] = [ProjectAborted(project_id=self.project_id, reason=reason)]
        for t in self._tasks.values():
            if t["status"] not in TERMINAL_TASK_STATES:
                t["status"] = TaskState.ABORTED
        return events

    # ── Task transitions ──────────────────────────────────

    def complete_task(self, task_id: str) -> list[DomainEvent]:
        self._transition_task(task_id, TaskState.DONE)
        events: list[DomainEvent] = [
            TaskCompleted(project_id=self.project_id, task_id=task_id),
        ]
        events.extend(self._activate_ready_tasks())
        events.append(self._calc_progress())

        if self._all_tasks_terminal():
            events.extend(self._finalize_project())

        return events

    def fail_task(self, task_id: str, error: str = "") -> list[DomainEvent]:
        self._transition_task(task_id, TaskState.FAILED)
        events: list[DomainEvent] = [
            TaskFailed(project_id=self.project_id, task_id=task_id, error=error),
        ]
        events.extend(self._block_downstream(task_id))
        events.append(self._calc_progress())
        return events

    def validation_fail_task(self, task_id: str, errors: list[str]) -> list[DomainEvent]:
        self._transition_task(task_id, TaskState.VALIDATION_FAILED)
        events: list[DomainEvent] = [
            TaskValidationFailed(
                project_id=self.project_id, task_id=task_id, errors=errors),
        ]
        events.extend(self._block_downstream(task_id))
        return events

    def retry_task(self, task_id: str) -> list[DomainEvent]:
        self._transition_task(task_id, TaskState.RUNNING)
        for t in self._tasks.values():
            if t["status"] == TaskState.BLOCKED:
                blocked_by = self._get_failed_deps(t["id"])
                if not blocked_by:
                    self._transition_task(t["id"], TaskState.PENDING)
        return [TaskStarted(project_id=self.project_id, task_id=task_id)]

    # ── Query helpers ─────────────────────────────────────

    def get_task(self, task_id: str) -> dict:
        return self._tasks[task_id]

    def get_all_tasks(self) -> list[dict]:
        return list(self._tasks.values())

    def get_running_tasks(self) -> list[dict]:
        return [t for t in self._tasks.values() if t["status"] == TaskState.RUNNING]

    def get_ready_tasks(self) -> list[dict]:
        """Tasks whose deps are all done and that are pending."""
        ready = []
        for t in self._tasks.values():
            if t["status"] != TaskState.PENDING:
                continue
            deps = t.get("deps", [])
            if all(self._tasks[d]["status"] == TaskState.DONE for d in deps if d in self._tasks):
                ready.append(t)
        return ready

    @property
    def progress_pct(self) -> float:
        if not self._tasks:
            return 0.0
        done = sum(1 for t in self._tasks.values() if t["status"] == TaskState.DONE)
        return round(done / len(self._tasks) * 100, 1)

    # ── Internal ──────────────────────────────────────────

    def _transition_project(self, new_state: ProjectState) -> None:
        allowed = PROJECT_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise InvalidTransition(
                f"Project {self.project_id}: {self.state} → {new_state} not allowed")
        self.state = new_state

    def _transition_task(self, task_id: str, new_state: TaskState) -> None:
        task = self._tasks[task_id]
        current = TaskState(task["status"])
        allowed = TASK_TRANSITIONS.get(current, set())
        if new_state not in allowed:
            raise InvalidTransition(
                f"Task {task_id}: {current} → {new_state} not allowed")
        task["status"] = new_state

    def _activate_ready_tasks(self) -> list[DomainEvent]:
        events = []
        for t in self.get_ready_tasks():
            self._transition_task(t["id"], TaskState.RUNNING)
            events.append(TaskStarted(project_id=self.project_id, task_id=t["id"]))
        return events

    def _block_downstream(self, failed_task_id: str) -> list[DomainEvent]:
        events = []
        for t in self._tasks.values():
            if t["status"] in TERMINAL_TASK_STATES or t["status"] == TaskState.BLOCKED:
                continue
            deps = t.get("deps", [])
            if failed_task_id in deps:
                if t["status"] in (TaskState.PENDING, TaskState.PAUSED):
                    t["status"] = TaskState.BLOCKED
                    events.append(TaskBlocked(
                        project_id=self.project_id,
                        task_id=t["id"],
                        blocked_by=[failed_task_id],
                    ))
        return events

    def _get_failed_deps(self, task_id: str) -> list[str]:
        task = self._tasks[task_id]
        deps = task.get("deps", [])
        return [d for d in deps if d in self._tasks
                and TaskState(self._tasks[d]["status"]) in FAILED_TASK_STATES]

    def _all_tasks_terminal(self) -> bool:
        return all(TaskState(t["status"]) in TERMINAL_TASK_STATES
                   for t in self._tasks.values())

    def _finalize_project(self) -> list[DomainEvent]:
        final_qa = [t for t in self._tasks.values() if t.get("kind") == "final_qa"]

        if final_qa:
            qa_task = final_qa[0]
            if qa_task["status"] == TaskState.DONE:
                verdict = qa_task.get("qa_verdict", "pass")
            else:
                verdict = "fail"
        else:
            has_failures = any(
                TaskState(t["status"]) in FAILED_TASK_STATES
                for t in self._tasks.values()
            )
            verdict = "fail" if has_failures else "pass"

        state_map = {
            "pass": ProjectState.COMPLETED,
            "warn": ProjectState.COMPLETED_WITH_WARNINGS,
            "fail": ProjectState.COMPLETED_WITH_ISSUES,
        }
        new_state = state_map.get(verdict, ProjectState.COMPLETED_WITH_ISSUES)
        self.state = new_state

        return [ProjectCompleted(project_id=self.project_id, verdict=verdict)]

    def _calc_progress(self) -> ProjectProgress:
        return ProjectProgress(project_id=self.project_id, progress_pct=self.progress_pct)
