from __future__ import annotations

from enum import StrEnum


class ProjectState(StrEnum):
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    COMPLETED_WITH_ISSUES = "completed_with_issues"
    ABORTED = "aborted"


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    ABORTED = "aborted"
    VALIDATION_FAILED = "validation_failed"
    BLOCKED = "blocked"


PROJECT_TRANSITIONS: dict[ProjectState, set[ProjectState]] = {
    ProjectState.READY: {ProjectState.RUNNING, ProjectState.ABORTED},
    ProjectState.RUNNING: {ProjectState.PAUSED, ProjectState.COMPLETED,
                           ProjectState.COMPLETED_WITH_WARNINGS,
                           ProjectState.COMPLETED_WITH_ISSUES, ProjectState.ABORTED},
    ProjectState.PAUSED: {ProjectState.RUNNING, ProjectState.ABORTED},
    ProjectState.COMPLETED: set(),
    ProjectState.COMPLETED_WITH_WARNINGS: set(),
    ProjectState.COMPLETED_WITH_ISSUES: set(),
    ProjectState.ABORTED: set(),
}

TASK_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {TaskState.RUNNING, TaskState.BLOCKED, TaskState.ABORTED},
    TaskState.RUNNING: {TaskState.DONE, TaskState.FAILED, TaskState.PAUSED,
                        TaskState.VALIDATION_FAILED, TaskState.ABORTED},
    TaskState.PAUSED: {TaskState.RUNNING, TaskState.ABORTED},
    TaskState.DONE: set(),
    TaskState.FAILED: {TaskState.RUNNING, TaskState.ABORTED},
    TaskState.ABORTED: set(),
    TaskState.VALIDATION_FAILED: {TaskState.RUNNING, TaskState.ABORTED},
    TaskState.BLOCKED: {TaskState.PENDING, TaskState.ABORTED},
}

TERMINAL_TASK_STATES = {TaskState.DONE, TaskState.FAILED, TaskState.ABORTED,
                         TaskState.VALIDATION_FAILED}
FAILED_TASK_STATES = {TaskState.FAILED, TaskState.VALIDATION_FAILED, TaskState.ABORTED}
