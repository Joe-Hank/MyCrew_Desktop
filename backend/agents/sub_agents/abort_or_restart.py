"""Abort / restart sub-agent — no LLM call.

User said "算了不做了" / "重新开始" / "清空重新选". We:
  1. If session has a draft project (project_id set + state='ready' + 0 tasks done),
     delete that project + cascade tasks/inception messages → effectively reset
  2. Reset session.template_id to NULL so the front-end re-shows
     InitialTemplateChoice
  3. Return a short confirmation message

This is a pure DB / session operation — no LLM call.
"""
from __future__ import annotations

import structlog

from agents.sub_agents._base import SubAgentResult, empty_result
from infra.repo import crud

log = structlog.get_logger()


async def run(user_message: str, session: dict) -> SubAgentResult:
    session_id = session.get("id") or ""
    project_id = session.get("project_id")

    purged_project = False
    if project_id:
        # Only purge if the project hasn't actually started
        project = await crud.get_by_id("projects", project_id)
        if project and project.get("state") == "ready" and not project.get("is_running"):
            tasks = await crud.get_all(
                "tasks", "project_id = ?", (project_id,),
            )
            done_count = sum(1 for t in tasks if t.get("status") == "done")
            if done_count == 0:
                # Safe to delete
                for t in tasks:
                    await crud.delete_by_id("tasks", t["id"])
                await crud.delete_by_id("projects", project_id)
                purged_project = True
                log.info("abort_or_restart.project_purged",
                         project_id=project_id, session_id=session_id)

    # Reset session template + project binding so front-end re-shows
    # InitialTemplateChoice
    updates: dict = {}
    if session.get("template_id"):
        updates["template_id"] = None
    if session.get("project_id"):
        updates["project_id"] = None
    if updates:
        await crud.update_by_id("inception_sessions", session_id, updates)

    if purged_project:
        msg = "好的，已清空当前草稿。请重新选择模板开始新的设计。"
    else:
        msg = "好的，已重置选择。请重新选择模板开始新的设计。"

    return {
        "reply_text": msg,
        "project_id": None,
        "blueprint": None,
        "metadata": {
            "sub_agent": "abort_or_restart",
            "purged_project": purged_project,
        },
    }
