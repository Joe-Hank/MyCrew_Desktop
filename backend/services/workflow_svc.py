from __future__ import annotations

import structlog

log = structlog.get_logger()


class WorkflowService:
    async def start(self, project_id: str) -> None:
        raise NotImplementedError

    async def pause(self, project_id: str) -> None:
        raise NotImplementedError

    async def resume(self, project_id: str) -> None:
        raise NotImplementedError

    async def recover(self) -> list[str]:
        return []

    async def pause_all(self) -> int:
        return 0


workflow_svc = WorkflowService()
