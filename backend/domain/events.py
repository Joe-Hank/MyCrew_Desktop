from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DomainEvent:
    ts: str = field(default_factory=_now)


# ── Project-level events ──────────────────────────────────

@dataclass(frozen=True)
class ProjectStarted(DomainEvent):
    project_id: str = ""

@dataclass(frozen=True)
class ProjectPaused(DomainEvent):
    project_id: str = ""

@dataclass(frozen=True)
class ProjectResumed(DomainEvent):
    project_id: str = ""

@dataclass(frozen=True)
class ProjectCompleted(DomainEvent):
    project_id: str = ""
    verdict: str = "pass"

@dataclass(frozen=True)
class ProjectAborted(DomainEvent):
    project_id: str = ""
    reason: str = ""

@dataclass(frozen=True)
class ProjectProgress(DomainEvent):
    project_id: str = ""
    progress_pct: float = 0.0


# ── Task-level events ─────────────────────────────────────

@dataclass(frozen=True)
class TaskStarted(DomainEvent):
    project_id: str = ""
    task_id: str = ""

@dataclass(frozen=True)
class TaskCompleted(DomainEvent):
    project_id: str = ""
    task_id: str = ""

@dataclass(frozen=True)
class TaskFailed(DomainEvent):
    project_id: str = ""
    task_id: str = ""
    error: str = ""

@dataclass(frozen=True)
class TaskValidationFailed(DomainEvent):
    project_id: str = ""
    task_id: str = ""
    errors: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class TaskPaused(DomainEvent):
    project_id: str = ""
    task_id: str = ""

@dataclass(frozen=True)
class TaskBlocked(DomainEvent):
    project_id: str = ""
    task_id: str = ""
    blocked_by: list[str] = field(default_factory=list)


# ── Interaction events ────────────────────────────────────

@dataclass(frozen=True)
class PromptRequested(DomainEvent):
    project_id: str = ""
    task_id: str = ""
    request_id: str = ""
    prompt_type: str = "confirm"
    options: list[str] = field(default_factory=list)
    hint: str = ""
