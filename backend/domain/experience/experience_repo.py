"""Experience repository — domain abstraction of CrewAI long-term memory."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExperienceEntry:
    id: str = ""
    agent_id: str = ""
    task_id: str = ""
    project_id: str = ""
    tags: list[str] = field(default_factory=list)
    content: str = ""
    embedding: list[float] | None = None
    score: float = 0.0


@dataclass
class ExperienceQuery:
    agent_id: str | None = None
    tags: list[str] = field(default_factory=list)
    query_text: str = ""
    limit: int = 5


class ExperiencePort:
    """Protocol for experience storage — implemented by infra layer."""

    async def save(self, entry: ExperienceEntry) -> str:
        raise NotImplementedError

    async def search(self, query: ExperienceQuery) -> list[ExperienceEntry]:
        raise NotImplementedError

    async def delete(self, entry_id: str) -> bool:
        raise NotImplementedError

    async def get_by_task(self, task_id: str) -> list[ExperienceEntry]:
        raise NotImplementedError
