"""SQLite-backed implementation of ExperiencePort.

Schema is created by migration `0003_experiences`. Search is a simple
LIKE-based scan + tag overlap for MVP — vector search is deferred (plan §17).
"""
from __future__ import annotations

import json

import structlog

from domain.experience.experience_repo import (
    ExperienceEntry,
    ExperienceQuery,
)
from infra.repo import crud

log = structlog.get_logger()


def _row_to_entry(row: dict) -> ExperienceEntry:
    tags = row.get("tags", "[]")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = []
    return ExperienceEntry(
        id=row.get("id", ""),
        agent_id=row.get("agent_id", ""),
        task_id=row.get("task_id", "") or "",
        project_id=row.get("project_id", "") or "",
        tags=tags,
        content=row.get("content", ""),
        embedding=None,
        score=float(row.get("score", 0) or 0),
    )


class SqliteExperienceRepo:
    """Implements `domain.experience.experience_repo.ExperiencePort`."""

    async def save(self, entry: ExperienceEntry) -> str:
        row = await crud.insert("experiences", {
            "agent_id": entry.agent_id,
            "task_id": entry.task_id or None,
            "project_id": entry.project_id or None,
            "tags": json.dumps(entry.tags),
            "content": entry.content,
            "score": entry.score,
        }, id_prefix="exp_")
        log.info("experience.saved", id=row["id"], agent_id=entry.agent_id)
        return row["id"]

    async def search(self, query: ExperienceQuery) -> list[ExperienceEntry]:
        where_parts: list[str] = []
        params: list = []
        if query.agent_id:
            where_parts.append("agent_id = ?")
            params.append(query.agent_id)
        if query.query_text:
            where_parts.append("content LIKE ?")
            params.append(f"%{query.query_text}%")
        where = " AND ".join(where_parts) if where_parts else ""

        rows = await crud.get_all("experiences", where, tuple(params))

        # Tag filtering done in Python (SQLite doesn't natively grok JSON arrays)
        if query.tags:
            tag_set = set(query.tags)
            filtered: list[dict] = []
            for r in rows:
                row_tags = r.get("tags", "[]")
                if isinstance(row_tags, str):
                    try:
                        row_tags = json.loads(row_tags)
                    except (json.JSONDecodeError, TypeError):
                        row_tags = []
                if tag_set.intersection(set(row_tags or [])):
                    filtered.append(r)
            rows = filtered

        # Most recent first (created_at DESC)
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return [_row_to_entry(r) for r in rows[: query.limit]]

    async def delete(self, entry_id: str) -> bool:
        return await crud.delete_by_id("experiences", entry_id)

    async def get_by_task(self, task_id: str) -> list[ExperienceEntry]:
        rows = await crud.get_all("experiences", "task_id = ?", (task_id,))
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return [_row_to_entry(r) for r in rows]


experience_repo = SqliteExperienceRepo()
