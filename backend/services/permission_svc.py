from __future__ import annotations

import structlog

from infra.repo import crud
from infra.repo.sqlite_repo import get_db

log = structlog.get_logger()


class PermissionService:
    async def get_permissions(self) -> list[dict]:
        rows = await crud.get_all("permissions")
        return [
            {**r, "allowed": bool(r.get("allowed", 1))}
            for r in rows
        ]

    async def update_permissions(self, updates: list[dict]) -> list[dict]:
        db = await get_db()
        for u in updates:
            await db.execute(
                "UPDATE permissions SET allowed = ? WHERE id = ?",
                (1 if u["allowed"] else 0, u["id"]),
            )
        await db.commit()
        log.info("permissions.updated", count=len(updates))
        return await self.get_permissions()

    async def check(self, kind: str, target: str = "*") -> bool:
        db = await get_db()
        cursor = await db.execute(
            "SELECT allowed FROM permissions WHERE kind = ?", (kind,)
        )
        row = await cursor.fetchone()
        if row is None:
            return True
        return bool(row[0])


permission_svc = PermissionService()
