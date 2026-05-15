"""Create-new sub-agent — v3 thin entry that delegates to the 5-phase Crew.

The actual 5-phase orchestration lives in `_planner_orchestrator.run_crew`.
This file's only job is to be the router-facing entry point with the
right SubAgentResult signature.

The v2 "single kickoff + 3 tool calls + post-hoc self-heal" approach is
gone. Per-phase Pydantic-enforced submit tools + in-memory draft cache
replaced it. See docs/iterations/2026-05-15/pm-v3-plan.md for full
rationale.

Cache semantics:
  - All phase outputs + final draft blueprint live in
    services.planner_cache_svc._sessions[session_id]
  - NOT persisted to DB until the user clicks "保存项目" (handled by
    routes_pm.py's pm_save endpoint via planner_persist_svc)
  - Cleared on: 保存 / 新建对话 / 关程序 / 用户取消
"""
from __future__ import annotations

import structlog

from agents.sub_agents._base import SubAgentResult, empty_result

log = structlog.get_logger()


# DEFAULT_PARAMS retained for compatibility with the router's intent
# classifier expectations, even though v3 uses per-phase tuning inside
# the orchestrator.
DEFAULT_PARAMS = {
    "llm_preference": "pro",
    "temperature": 0.5,
    "max_tokens": 4000,
}


async def run(user_message: str, session: dict) -> SubAgentResult:
    """Router entry. Drives the 5-phase Crew and returns a reply.

    The reply is short ("草稿已生成 / 失败 / 取消") — the rich content
    (debug log + draft blueprint + 保存 button) is delivered to the
    drawer via WS events (pm.log) + the pm_state endpoint.
    """
    session_id = session.get("id") or ""

    # Hard precondition (router should have caught this, but defense in depth)
    if (session.get("mode") or "create").lower() == "create" and not session.get("template_id"):
        return empty_result(
            "请先在上方卡片中选择一个 Unity 模板，我才能开始拆解任务。"
        )

    from agents.sub_agents._planner_orchestrator import run_crew
    from services import planner_cache_svc

    # Don't run a second crew on top of one already in flight.
    if planner_cache_svc.is_running(session_id):
        return {
            "reply_text": "Plan Maker 工作流正在跑动中，请等待它完成（或点 Stop 取消）。",
            "project_id": None,
            "blueprint": None,
            "metadata": {"sub_agent": "create_new", "pm_state": "already_running"},
        }

    draft = await run_crew(session, user_message)
    status = draft.get("status", "failed")

    if status == "ready":
        reply = (
            "草稿已生成。点击右侧的『保存项目』可以把它落到 DB + .mycrew/；"
            "或者在蓝图编辑器里继续微调，然后再保存。"
        )
    elif status == "cancelled":
        reply = "工作流已取消。"
    elif status == "failed":
        failed = draft.get("failed_phase") or "(unknown)"
        err = draft.get("error") or "(unknown)"
        reply = (
            f"工作流在 phase '{failed}' 失败：{err}\n"
            "你可以点右侧的『从断点重来』按钮重试该 phase，"
            "或者直接重发一条新的消息整轮重来。"
        )
    else:
        reply = "工作流状态未知，请查看右侧日志。"

    return {
        "reply_text": reply,
        "project_id": None,        # cache-first: nothing in DB until 保存
        "blueprint": None,         # broadcast separately via pm.log + pm_state
        "metadata": {"sub_agent": "create_new", "pm_state": status},
    }
