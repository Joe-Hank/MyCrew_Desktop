from __future__ import annotations

import json

import structlog

from infra.repo import crud

log = structlog.get_logger()

JSON_FIELDS = ["deps"]


class ProjectService:
    async def list_projects(self, page: int = 1, size: int = 4) -> dict:
        result = await crud.paginate("projects", page=page, size=size,
                                      order_by="created_at DESC")
        for item in result["items"]:
            tasks = await crud.get_all("tasks", "project_id = ?", (item["id"],))
            total = len(tasks)
            done = sum(1 for t in tasks if t.get("status") == "done")
            item["task_count"] = total
            item["done_count"] = done
            item["progress_pct"] = round(done / total * 100, 1) if total else 0
        return result

    async def get_project(self, project_id: str) -> dict | None:
        row = await crud.get_by_id("projects", project_id)
        if not row:
            return None
        project = dict(row)
        tasks = await crud.get_all("tasks", "project_id = ?", (project_id,))
        project["tasks"] = [self._deserialize_task(t) for t in tasks]
        return project

    async def create_project(self, data: dict) -> dict:
        row = await crud.insert("projects", {
            "name": data["name"],
            "root_path": data.get("root_path"),
            "state": "ready",
            "is_running": 0,
            "progress_pct": 0,
            "execution_kind": data.get("execution_kind", "sequential"),
        }, id_prefix="proj_")
        log.info("project.created", id=row["id"], name=data["name"])
        return row

    async def create_project_with_tasks(self, data: dict, tasks: list[dict]) -> dict:
        project = await self.create_project(data)
        project_id = project["id"]

        for t in tasks:
            await crud.insert("tasks", {
                "project_id": project_id,
                "title": t["title"],
                "detail": t.get("detail", ""),
                "agent_id": t.get("agent_id"),
                "kind": t.get("kind", "regular"),
                "output_schema": json.dumps(t.get("output_schema", {})),
                "status": "pending",
                "deps": json.dumps(t.get("deps", [])),
            }, id_prefix="task_")

        log.info("project.created_with_tasks",
                 id=project_id, task_count=len(tasks))
        return await self.get_project(project_id)

    async def clone_project(self, project_id: str) -> dict:
        source = await self.get_project(project_id)
        if not source:
            raise KeyError(f"Project {project_id} not found")

        new_project = await crud.insert("projects", {
            "name": f"{source['name']} (副本)",
            "state": "ready",
            "is_running": 0,
            "progress_pct": 0,
            "execution_kind": source.get("execution_kind", "sequential"),
            "copied_from": project_id,
        }, id_prefix="proj_")

        old_to_new: dict[str, str] = {}
        for t in source.get("tasks", []):
            new_task = await crud.insert("tasks", {
                "project_id": new_project["id"],
                "title": t["title"],
                "detail": t.get("detail", ""),
                "agent_id": t.get("agent_id"),
                "kind": t.get("kind", "regular"),
                "output_schema": json.dumps(t.get("output_schema", {})),
                "status": "pending",
                "deps": "[]",
            }, id_prefix="task_")
            old_to_new[t["id"]] = new_task["id"]

        for t in source.get("tasks", []):
            old_deps = t.get("deps", [])
            if isinstance(old_deps, str):
                old_deps = json.loads(old_deps)
            new_deps = [old_to_new[d] for d in old_deps if d in old_to_new]
            if new_deps:
                new_id = old_to_new[t["id"]]
                await crud.update_by_id("tasks", new_id, {
                    "deps": json.dumps(new_deps),
                })

        log.info("project.cloned", source=project_id, new_id=new_project["id"])
        return await self.get_project(new_project["id"])

    async def delete_project(self, project_id: str) -> None:
        tasks = await crud.get_all("tasks", "project_id = ?", (project_id,))
        for t in tasks:
            await crud.delete_by_id("tasks", t["id"])

        sessions = await crud.get_all("inception_sessions",
                                       "project_id = ?", (project_id,))
        for s in sessions:
            msgs = await crud.get_all("inception_messages",
                                       "session_id = ?", (s["id"],))
            for m in msgs:
                await crud.delete_by_id("inception_messages", m["id"])
            await crud.delete_by_id("inception_sessions", s["id"])

        await crud.delete_by_id("projects", project_id)
        log.info("project.deleted", id=project_id)

    async def update_root_path(self, project_id: str, root_path: str) -> dict | None:
        return await crud.update_by_id("projects", project_id, {
            "root_path": root_path,
        })

    def _deserialize_task(self, row: dict) -> dict:
        t = dict(row)
        for f in ("deps", "output_schema"):
            if f in t and isinstance(t[f], str):
                try:
                    t[f] = json.loads(t[f])
                except (json.JSONDecodeError, TypeError):
                    t[f] = [] if f == "deps" else {}
        return t


project_svc = ProjectService()
