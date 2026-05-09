from __future__ import annotations

import structlog

log = structlog.get_logger()


class PermissionService:
    async def get_permissions(self) -> list[dict]:
        return []

    async def update_permissions(self, permissions: list[dict]) -> list[dict]:
        raise NotImplementedError

    async def check(self, kind: str, target: str = "*") -> bool:
        return True


permission_svc = PermissionService()
