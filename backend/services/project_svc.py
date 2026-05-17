from __future__ import annotations

import json

import structlog

from infra.repo import crud

log = structlog.get_logger()

JSON_FIELDS = ["deps"]


class ProjectService:
    # Compound sort key for the home grid, matching the spec exactly:
    #
    #   1. Favorited rows first.            ← (favorited_at IS NULL) puts NULLs last
    #   2. Within favorites: newest star first.
    #   3. Within non-favorites: by MAX(unfavorited_at, created_at) DESC, so a
    #      project just unstarred jumps to the head of the non-favorited
    #      group, same position a newly created project would land in.
    LIST_ORDER_BY = (
        "(favorited_at IS NULL), "
        "favorited_at DESC, "
        "COALESCE(unfavorited_at, created_at) DESC"
    )

    async def list_projects(self, page: int = 1, size: int = 4) -> dict:
        result = await crud.paginate("projects", page=page, size=size,
                                      order_by=self.LIST_ORDER_BY)
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
        # PM v5+ (2026-05-17): when a Unity template is bound to the
        # project, mark scaffold_status='pending' so workflow_svc.start
        # demands a root_parent_path + slug from the user before the
        # first run. Plain (no-template) projects skip scaffold entirely.
        from services.template_cloner_svc import TEMPLATE_ID_TO_DIR
        tmpl = data.get("template_id")
        scaffold_status = (
            "pending"
            if tmpl in TEMPLATE_ID_TO_DIR else None
        )
        row = await crud.insert("projects", {
            "name": data["name"],
            "root_path": data.get("root_path"),
            "template_id": tmpl,
            "state": "ready",
            "is_running": 0,
            "progress_pct": 0,
            "execution_kind": data.get("execution_kind", "sequential"),
            "scaffold_status": scaffold_status,
        }, id_prefix="proj_")
        log.info("project.created",
                 id=row["id"], name=data["name"],
                 template_id=tmpl, scaffold_status=scaffold_status)
        return row

    async def create_project_with_tasks(self, data: dict, tasks: list[dict]) -> dict:
        """Persist a Project + Tasks pair, translating Plan Maker's
        0-based dep indices into real task ids.

        Two-pass insert:
          1. Insert each task with empty deps; remember its array index →
             newly-allocated task id.
          2. Walk each task's `deps`; ints map back through the index
             table to task ids; strings are assumed to already be task
             ids (so callers that already hold task ids can pass them
             through). UPDATE the row only when deps are non-empty.

        Compensating-write transaction model (audit 2026-05-16, Top 5 #4):
        SQLite + aiosqlite each crud op auto-commits, so we can't wrap the
        two passes in a single BEGIN/COMMIT without rewriting crud. Instead
        we catch any exception during passes 1-2 and roll back manually by
        calling delete_project — which cascades to the partially-inserted
        tasks. Net effect: caller sees either a fully-created project or a
        clean failure with no orphan rows.
        """
        project = await self.create_project(data)
        project_id = project["id"]

        try:
            # Pass 1: insert empty-dep tasks, build index → task_id map.
            index_to_id: dict[int, str] = {}
            for i, t in enumerate(tasks):
                # PM v5: code_contract is a dict from the blueprint (or
                # None for non-code tasks). Serialize once here; the
                # crewai_runner pulls it back via crud.get_by_id when
                # building Crew QA step bindings.
                code_contract = t.get("code_contract")
                contract_json = (
                    json.dumps(code_contract, ensure_ascii=False)
                    if isinstance(code_contract, dict) else None
                )
                # 2026-05-17 (Plan A): Phase 4 LLM produces detailed
                # output_paths per task (sprite list / .cs paths / etc.),
                # but the prior INSERT silently dropped them. Tasks ended
                # up with NULL output_paths → Crew Executors saw "[]" in
                # their contract block and did nothing (audio task: zero
                # .wav produced) or improvised from task.detail prose
                # alone (art task: only Player sprites). Persist the
                # list so emit_output verification, Crew step
                # description, and code-contract phase all see the
                # truth.
                paths = t.get("output_paths") or []
                output_paths_json = (
                    json.dumps(paths, ensure_ascii=False)
                    if isinstance(paths, list) else None
                )
                row = await crud.insert("tasks", {
                    "project_id": project_id,
                    "title": t["title"],
                    "detail": t.get("detail", ""),
                    "agent_id": t.get("agent_id"),
                    "kind": t.get("kind", "regular"),
                    "output_schema": json.dumps(t.get("output_schema", {})),
                    "status": "pending",
                    "deps": "[]",
                    # PM v4: performer_kind / performer_id route execution
                    # (agent path vs Crew walker). Legacy agent_id is kept
                    # for iterate_existing + the team page tag.
                    "performer_kind": t.get("performer_kind"),
                    "performer_id": t.get("performer_id"),
                    # PM v5: named-symbol contract for Crew QA verification.
                    "code_contract": contract_json,
                    # PM Phase 4 output: the explicit must-produce file
                    # paths. Empty list = "no files expected" (e.g. setup
                    # / final_qa tasks). NULL = legacy row from before
                    # this fix.
                    "output_paths": output_paths_json,
                }, id_prefix="task_")
                index_to_id[i] = row["id"]

            # Pass 2: translate dep references and patch each task that
            # actually has upstream dependencies. Mixed int/str arrays are
            # tolerated so callers that supply real task ids still work.
            for i, t in enumerate(tasks):
                raw_deps = t.get("deps") or []
                translated: list[str] = []
                for d in raw_deps:
                    if isinstance(d, int):
                        mapped = index_to_id.get(d)
                        if mapped:
                            translated.append(mapped)
                    elif isinstance(d, str) and d:
                        translated.append(d)
                if translated:
                    await crud.update_by_id("tasks", index_to_id[i], {
                        "deps": json.dumps(translated),
                    })
        except Exception as exc:
            # Compensate: drop the half-created project + every task we
            # managed to insert. delete_project iterates tasks by
            # project_id so it catches everything Pass 1 wrote, plus any
            # sessions/messages that happened to attach.
            log.error("project.create_with_tasks_failed_rolling_back",
                      project_id=project_id, error=str(exc))
            try:
                await self.delete_project(project_id)
            except Exception as cleanup_exc:  # noqa: BLE001
                log.error("project.rollback_failed",
                          project_id=project_id, error=str(cleanup_exc))
            raise

        log.info("project.created_with_tasks",
                 id=project_id, task_count=len(tasks))
        return await self.get_project(project_id)

    async def clone_project(self, project_id: str) -> dict:
        source = await self.get_project(project_id)
        if not source:
            raise KeyError(f"Project {project_id} not found")

        # 2026-05-17: a Unity-template clone has to keep its template_id,
        # otherwise ProjectCard.isScaffoldable goes false on the new card
        # and the 「路径」 button falls through to the bare Tauri folder
        # picker instead of opening ScaffoldConfigModal — the bug the
        # user just reported as "复制出来的卡片第一次点路径没有正确弹窗".
        # Reset scaffold_status to 'pending' so the user is prompted for
        # a fresh parent_dir + slug (reusing the source's child dir
        # would collide). Plain (no-template) clones leave both NULL.
        from services.template_cloner_svc import TEMPLATE_ID_TO_DIR
        source_tmpl = source.get("template_id")
        scaffold_status = (
            "pending" if source_tmpl in TEMPLATE_ID_TO_DIR else None
        )

        new_project = await crud.insert("projects", {
            "name": f"{source['name']} (副本)",
            "template_id": source_tmpl,
            "state": "ready",
            "is_running": 0,
            "progress_pct": 0,
            "execution_kind": source.get("execution_kind", "sequential"),
            "copied_from": project_id,
            "scaffold_status": scaffold_status,
        }, id_prefix="proj_")

        old_to_new: dict[str, str] = {}
        for t in source.get("tasks", []):
            # Preserve PM v4/v5 fields too: without performer_kind /
            # performer_id the clone fails the _start_locked performer
            # check; without code_contract / output_paths the Crew
            # Executors see an empty contract and silently exit (the
            # same root cause as the 魔塔 audio failure). Re-serialize
            # the dict/list fields since _deserialize_task already
            # parsed them on read.
            src_contract = t.get("code_contract")
            contract_json = (
                json.dumps(src_contract, ensure_ascii=False)
                if isinstance(src_contract, dict) else None
            )
            src_paths = t.get("output_paths")
            if isinstance(src_paths, str) and src_paths:
                try:
                    src_paths = json.loads(src_paths)
                except (json.JSONDecodeError, TypeError):
                    src_paths = None
            output_paths_json = (
                json.dumps(src_paths, ensure_ascii=False)
                if isinstance(src_paths, list) else None
            )

            new_task = await crud.insert("tasks", {
                "project_id": new_project["id"],
                "title": t["title"],
                "detail": t.get("detail", ""),
                "agent_id": t.get("agent_id"),
                "kind": t.get("kind", "regular"),
                "output_schema": json.dumps(t.get("output_schema", {})),
                "status": "pending",
                "deps": "[]",
                "performer_kind": t.get("performer_kind"),
                "performer_id": t.get("performer_id"),
                "code_contract": contract_json,
                "output_paths": output_paths_json,
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

    async def favorite(self, project_id: str) -> dict | None:
        """Star the project. Sets favorited_at = now and clears
        unfavorited_at so the row jumps to the head of the favorites tier
        in the list ORDER BY."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return await crud.update_by_id("projects", project_id, {
            "favorited_at": now,
            "unfavorited_at": None,
        })

    async def unfavorite(self, project_id: str) -> dict | None:
        """Unstar the project. Clears favorited_at and stamps
        unfavorited_at = now so the row jumps to the head of the
        non-favorited tier (where new projects also land)."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        return await crud.update_by_id("projects", project_id, {
            "favorited_at": None,
            "unfavorited_at": now,
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
