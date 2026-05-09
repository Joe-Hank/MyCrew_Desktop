from __future__ import annotations

import structlog

log = structlog.get_logger()


class ProjectService:
    async def list_projects(self, page: int = 1, size: int = 4) -> dict:
        return {"items": [], "total": 0, "page": page, "size": size}

    async def get_project(self, project_id: str) -> dict | None:
        return None

    async def create_project(self, data: dict) -> dict:
        raise NotImplementedError

    async def clone_project(self, project_id: str) -> dict:
        raise NotImplementedError

    async def delete_project(self, project_id: str) -> None:
        raise NotImplementedError

    async def update_root_path(self, project_id: str, root_path: str) -> dict:
        raise NotImplementedError

    async def start_project(self, project_id: str) -> dict:
        raise NotImplementedError

    async def pause_project(self, project_id: str) -> dict:
        raise NotImplementedError

    async def resume_project(self, project_id: str) -> dict:
        raise NotImplementedError


project_svc = ProjectService()
