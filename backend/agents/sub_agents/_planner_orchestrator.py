"""PM v3 — 5-phase Crew orchestrator.

Sequentially drives Phase 0 → 5, each phase a single CrewAI kickoff
with one strict-schema submit tool. Between phases we pop the validated
output via _output_capture, broadcast a `pm.log` event, store the
result in planner_cache_svc, and pass it forward.

Failure model (per the design):
  - Layer 1: CrewAI's own max_iter handles tool-validation retries
  - Layer 2: if max_iter exhausts with no captured output → ONE focused
    repair kickoff (same pro LLM, max_iter=3, with last error in prompt)
  - Layer 3: focused repair also fails → mark draft as failed,
    failed_phase=current, exit cleanly. Frontend sees "从断点重来"
    button + can resume from the failed phase.

`run_crew(session, user_message)` is the entry. It runs as the outer
HTTP handler awaits it; cancel comes via planner_cache_svc.request_cancel
which task.cancel()s the asyncio.Task.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import structlog

from agents._llm_picker import pick_llm
from agents.sub_agents._base import run_crewai_agent
from agents.sub_agents._planner_prompts import (
    COMPLETENESS_SYSTEM_PROMPT,
    PHASE1_BACKSTORY,
    PHASE1_GOAL,
    PHASE1_ROLE,
    PHASE2_BACKSTORY,
    PHASE2_GOAL,
    PHASE2_ROLE,
    PHASE3_BACKSTORY,
    PHASE3_GOAL,
    PHASE3_ROLE,
    PHASE4_GOAL,
    PHASE4_ROLE,
    PHASE5_GOAL,
    PHASE5_ROLE,
    phase4_backstory,
    phase5_backstory,
)
from agents.sub_agents._planner_tools import (
    make_submit_assignments_tool,
    make_submit_atomic_tasks_tool,
    make_submit_concept_tool,
    make_submit_pathed_tasks_tool,
    make_submit_reviewed_tasks_tool,
)
from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud
from services import planner_cache_svc
from src.tools.builtin.local._output_capture import (
    clear_planner_session,
    pop_planner_output,
)

log = structlog.get_logger()


# ── Per-phase config ────────────────────────────────────────────────


PHASES = ("concept", "system_design", "review", "project_mgmt", "agent_assignment")


# ── Public entry ────────────────────────────────────────────────────


async def run_crew(session: dict, user_message: str, start_from: str | None = None) -> dict[str, Any]:
    """Drive the 5-phase crew end-to-end.

    Returns the final draft entry (status='ready' on success,
    'failed' on giving up, 'cancelled' on user Stop).

    `start_from` enables "从断点重来" — if provided, we skip phases
    that already have output in the cache and resume from this phase.
    """
    session_id = session.get("id") or ""
    if not session_id:
        return {"status": "failed", "error": "no_session_id"}

    # Initialise the draft entry if this is a fresh round; else reuse
    # what's there (resume path).
    existing = planner_cache_svc.get(session_id)
    if existing is None or start_from is None:
        clear_planner_session(session_id)  # drop any stale per-phase captures
        planner_cache_svc.start_round(session_id)
    else:
        # Resume — reset status to running
        planner_cache_svc.update(
            session_id, status="running", error=None,
            failed_phase=None, current_phase=start_from,
        )

    try:
        # Pro LLM is used for every phase except Phase 0 (cheap binary
        # classifier). Resolved once and reused.
        pro_provider, pro_model = await pick_llm(session, "pro")
        cheap_provider, cheap_model = await pick_llm(session, "cheap")
    except (ValueError, KeyError) as exc:
        planner_cache_svc.update(session_id, status="failed",
                                  error=f"LLM 配置错误：{exc}")
        return planner_cache_svc.get(session_id) or {}

    try:
        # ── Phase 0: completeness ─────────────────────────────────
        if _need_run("completeness", start_from) and not _has_phase_output(session_id, "completeness"):
            await _broadcast(session_id, "completeness", "completeness 判定器",
                             "started", "判断输入是 ONELINE 还是 PRD")
            completeness = await _phase0_completeness(
                session_id, user_message, cheap_provider, cheap_model,
            )
            planner_cache_svc.update(session_id, completeness=completeness)
            planner_cache_svc.set_phase_output(session_id, "completeness", completeness)
            await _broadcast(session_id, "completeness", "completeness 判定器",
                             "phase_completed", f"判定为 {completeness}")
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        completeness = planner_cache_svc.get_phase_output(session_id, "completeness") or "ONELINE"

        # ── Phase 1: 主策划（PRD 跳过） ────────────────────────────
        if completeness == "ONELINE" and _need_run("concept", start_from) and not _has_phase_output(session_id, "concept"):
            planner_cache_svc.update(session_id, current_phase="concept")
            template_ctx = await _render_template_ctx(session)
            concept_dict = await _run_phase(
                session_id=session_id,
                phase="concept",
                role=PHASE1_ROLE, goal=PHASE1_GOAL,
                backstory=PHASE1_BACKSTORY,
                description=f"# 项目模板上下文\n{template_ctx}\n\n# 用户需求\n{user_message}",
                expected_output="调一次 submit_concept 提交 ConceptDoc 后一句中文确认。",
                tools=[make_submit_concept_tool(session_id)],
                provider=pro_provider, model_name=pro_model,
                temperature=0.7, max_tokens=4000,
            )
            planner_cache_svc.set_phase_output(session_id, "concept", concept_dict["concept"])
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 2: 系统策划 ──────────────────────────────────────
        if _need_run("system_design", start_from) and not _has_phase_output(session_id, "system_design"):
            planner_cache_svc.update(session_id, current_phase="system_design")
            concept = planner_cache_svc.get_phase_output(session_id, "concept")
            if concept is None:
                # PRD path — feed user_message directly
                phase2_input = f"# 用户提供的 PRD\n{user_message}"
            else:
                phase2_input = f"# 上游概念草案 (Phase 1)\n```json\n{json.dumps(concept, ensure_ascii=False, indent=2)}\n```"
            atomic_dict = await _run_phase(
                session_id=session_id,
                phase="system_design",
                role=PHASE2_ROLE, goal=PHASE2_GOAL,
                backstory=PHASE2_BACKSTORY,
                description=phase2_input,
                expected_output="调一次 submit_atomic_tasks 提交任务列表后一句中文确认。",
                tools=[make_submit_atomic_tasks_tool(session_id)],
                provider=pro_provider, model_name=pro_model,
                temperature=0.5, max_tokens=4000,
            )
            planner_cache_svc.set_phase_output(session_id, "system_design", atomic_dict["tasks"])
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 3: 审核策划 ──────────────────────────────────────
        if _need_run("review", start_from) and not _has_phase_output(session_id, "review"):
            planner_cache_svc.update(session_id, current_phase="review")
            atomic_tasks = planner_cache_svc.get_phase_output(session_id, "system_design")
            reviewed_dict = await _run_phase(
                session_id=session_id,
                phase="review",
                role=PHASE3_ROLE, goal=PHASE3_GOAL,
                backstory=PHASE3_BACKSTORY,
                description=(
                    "# 上游原子任务列表（系统策划 Phase 2 产物）\n"
                    "```json\n"
                    f"{json.dumps(atomic_tasks, ensure_ascii=False, indent=2)}\n"
                    "```\n\n"
                    "请审查并补充 acceptance_notes / input_sources / output_schema，调 submit_reviewed_tasks。"
                ),
                expected_output="调一次 submit_reviewed_tasks 提交后一句中文确认。",
                tools=[make_submit_reviewed_tasks_tool(session_id)],
                provider=pro_provider, model_name=pro_model,
                temperature=0.2, max_tokens=4000,
            )
            planner_cache_svc.set_phase_output(session_id, "review", reviewed_dict["tasks"])
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 4: 项目管理 ──────────────────────────────────────
        if _need_run("project_mgmt", start_from) and not _has_phase_output(session_id, "project_mgmt"):
            planner_cache_svc.update(session_id, current_phase="project_mgmt")
            reviewed = planner_cache_svc.get_phase_output(session_id, "review")
            template_ctx = await _render_template_ctx(session)
            initializer_id = await _get_initializer_agent_id()
            pathed_dict = await _run_phase(
                session_id=session_id,
                phase="project_mgmt",
                role=PHASE4_ROLE, goal=PHASE4_GOAL,
                backstory=phase4_backstory(template_ctx, initializer_id),
                description=(
                    "# 上游审核后的任务列表（Phase 3 产物）\n"
                    "```json\n"
                    f"{json.dumps(reviewed, ensure_ascii=False, indent=2)}\n"
                    "```\n\n"
                    f"# 项目初始化助手 agent_id（必须 pre-assign 给 tasks[0]）\n{initializer_id}\n\n"
                    "推导每个任务的 output_paths，前插 setup 任务，调 submit_pathed_tasks。"
                ),
                expected_output="调一次 submit_pathed_tasks 后一句中文确认。",
                tools=[make_submit_pathed_tasks_tool(session_id)],
                provider=pro_provider, model_name=pro_model,
                temperature=0.3, max_tokens=4000,
            )
            planner_cache_svc.set_phase_output(session_id, "project_mgmt", pathed_dict["tasks"])
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 5: Agent 指挥员 ──────────────────────────────────
        if _need_run("agent_assignment", start_from) and not _has_phase_output(session_id, "agent_assignment"):
            planner_cache_svc.update(session_id, current_phase="agent_assignment")
            pathed = planner_cache_svc.get_phase_output(session_id, "project_mgmt")
            agents_info = await _render_agents_info(session)
            assignments_dict = await _run_phase(
                session_id=session_id,
                phase="agent_assignment",
                role=PHASE5_ROLE, goal=PHASE5_GOAL,
                backstory=phase5_backstory(agents_info),
                description=(
                    "# 上游带路径的任务列表（Phase 4 产物）\n"
                    "```json\n"
                    f"{json.dumps(pathed, ensure_ascii=False, indent=2)}\n"
                    "```\n\n"
                    "跳过 tasks[0] 的 setup（已 pre-assigned），给其余每个任务匹配 agent，调 submit_assignments。"
                ),
                expected_output="调一次 submit_assignments 后一句中文确认。",
                tools=[make_submit_assignments_tool(session_id)],
                provider=pro_provider, model_name=pro_model,
                temperature=0.2, max_tokens=3000,
            )
            planner_cache_svc.set_phase_output(session_id, "agent_assignment",
                                                 assignments_dict["assignments"])

        # ── Assemble final draft blueprint ────────────────────────
        draft_blueprint = _assemble_draft_blueprint(session_id)
        planner_cache_svc.update(
            session_id,
            status="ready",
            current_phase="complete",
            draft_blueprint=draft_blueprint,
        )
        await _broadcast(session_id, "complete", "PM 工作流",
                         "phase_completed", "全部 5 个 phase 完成，草稿已就绪")
        return planner_cache_svc.get(session_id) or {}

    except asyncio.CancelledError:
        log.info("planner_orchestrator.cancelled", session_id=session_id)
        planner_cache_svc.update(session_id, status="cancelled")
        await _broadcast(session_id, "complete", "PM 工作流",
                         "cancelled", "用户取消了工作流")
        raise
    except Exception as exc:  # noqa: BLE001
        log.error("planner_orchestrator.failed",
                  session_id=session_id, error=str(exc))
        draft = planner_cache_svc.get(session_id) or {}
        planner_cache_svc.update(
            session_id,
            status="failed",
            error=str(exc),
            failed_phase=draft.get("current_phase"),
        )
        await _broadcast(session_id,
                         draft.get("current_phase") or "unknown",
                         "PM 工作流",
                         "phase_failed", f"工作流失败：{exc}",
                         error=str(exc))
        return planner_cache_svc.get(session_id) or {}


# ── Phase 0: cheap LLM 二分类 ──────────────────────────────────────


async def _phase0_completeness(
    session_id: str, user_message: str,
    cheap_provider: dict, cheap_model: str,
) -> str:
    messages = [
        LlmMessage(role="system", content=COMPLETENESS_SYSTEM_PROMPT),
        LlmMessage(role="user", content=user_message[:2000]),
    ]
    try:
        resp = await llm_gateway.chat(
            cheap_provider["id"], cheap_model, messages, max_tokens=10,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("planner.completeness_llm_failed",
                    session_id=session_id, error=str(exc))
        return "ONELINE"  # fail-open to ONELINE (safer)
    raw = (resp.text or "").strip().upper()
    return "PRD" if "PRD" in raw else "ONELINE"


# ── Generic phase runner with retry + focused repair ────────────────


async def _run_phase(
    *,
    session_id: str,
    phase: str,
    role: str, goal: str, backstory: str,
    description: str, expected_output: str,
    tools: list,
    provider: dict, model_name: str,
    temperature: float, max_tokens: int,
) -> dict:
    """Run one phase. Returns the captured payload dict on success.
    Raises on hard failure (after focused repair too)."""
    await _broadcast(session_id, phase, role, "started",
                     f"phase {phase} started")

    # Try 1: standard kickoff with max_iter=5
    try:
        await run_crewai_agent(
            session_id=session_id,
            role=role, goal=goal, backstory=backstory,
            description=description, expected_output=expected_output,
            tools=tools, provider=provider, model_name=model_name,
            max_iter=5, temperature=temperature, max_tokens=max_tokens,
            broadcast_steps=False,  # we emit pm.log separately
        )
    except Exception as exc:  # noqa: BLE001
        await _broadcast(session_id, phase, role, "phase_failed",
                         f"kickoff 异常：{exc}", error=str(exc))
        raise

    payload = pop_planner_output(session_id, phase)
    if payload is not None:
        await _broadcast(session_id, phase, role, "phase_completed",
                         f"phase {phase} completed",
                         payload_preview=payload)
        return payload

    # Try 2: focused repair — same prompt + "上一次没调工具"提示, max_iter=3
    await _broadcast(session_id, phase, role, "retry",
                     "未捕获到合法输出，焦点修复中…")
    repair_desc = (
        f"{description}\n\n"
        "# 重要：上一次你没成功调用提交工具或调用失败。\n"
        f"请这一次**务必调用** {tools[0].name} 工具一次性提交完整结果。"
    )
    try:
        await run_crewai_agent(
            session_id=session_id,
            role=role, goal=goal, backstory=backstory,
            description=repair_desc, expected_output=expected_output,
            tools=tools, provider=provider, model_name=model_name,
            max_iter=3, temperature=temperature, max_tokens=max_tokens,
            broadcast_steps=False,
        )
    except Exception as exc:  # noqa: BLE001
        await _broadcast(session_id, phase, role, "phase_failed",
                         f"焦点修复异常：{exc}", error=str(exc))
        raise

    payload = pop_planner_output(session_id, phase)
    if payload is not None:
        await _broadcast(session_id, phase, role, "phase_completed",
                         f"phase {phase} completed (repaired)",
                         payload_preview=payload)
        return payload

    msg = f"phase {phase}: agent 未能成功调用提交工具（max_iter + 焦点修复均失败）"
    await _broadcast(session_id, phase, role, "phase_failed", msg, error=msg)
    raise RuntimeError(msg)


# ── Helpers ─────────────────────────────────────────────────────────


async def _broadcast(
    session_id: str, phase: str, role: str, status: str, message: str,
    *, payload_preview: Any = None, detail: str | None = None,
    error: str | None = None,
) -> None:
    entry = {
        "session_id": session_id,
        "phase": phase,
        "role": role,
        "status": status,
        "ts": datetime.now(timezone.utc).isoformat(),
        "message": message,
        "payload_preview": payload_preview,
        "detail": detail,
        "error": error,
    }
    planner_cache_svc.append_log(session_id, entry)
    try:
        from api.ws import manager
        await manager.broadcast("pm.log", entry)
    except Exception:
        pass


def _check_cancelled(session_id: str) -> bool:
    d = planner_cache_svc.get(session_id)
    return bool(d and d.get("cancel_requested"))


def _has_phase_output(session_id: str, phase: str) -> bool:
    return planner_cache_svc.get_phase_output(session_id, phase) is not None


def _need_run(phase: str, start_from: str | None) -> bool:
    """When resuming, only run from start_from onward."""
    if start_from is None:
        return True
    # Both "completeness" → 0; phases ordered as defined.
    all_phases = ["completeness", "concept", "system_design", "review",
                  "project_mgmt", "agent_assignment"]
    return all_phases.index(phase) >= all_phases.index(start_from)


async def _render_template_ctx(session: dict) -> str:
    template_id = session.get("template_id") or ""
    if not template_id:
        return "（用户未选 Unity 模板，按通用 Unity 项目处理）"
    try:
        from data.unity_templates import render_template_context
        return render_template_context(template_id) or "（模板渲染为空）"
    except Exception as exc:  # noqa: BLE001
        log.warning("planner.template_render_failed", error=str(exc))
        return "（模板渲染失败）"


async def _get_initializer_agent_id() -> str:
    """Look up the seeded Project Initializer agent's id."""
    from bootstrap.seed_planner_agents import INITIALIZER_ROLE
    rows = await crud.get_all(
        "agents",
        "role = ? AND is_auto_generated = 0",
        (INITIALIZER_ROLE,),
    )
    if rows:
        return rows[0]["id"]
    return "agent_initializer_missing"  # surfaces in prompt → LLM will report


async def _render_agents_info(session: dict) -> str:
    """Render the available agents list for Phase 5's prompt."""
    rows = await crud.get_all("agents")
    # Exclude Plan Maker (orchestration role, not execution) and the
    # initializer (already pre-assigned to setup task).
    others = [
        r for r in rows
        if r.get("role") not in ("Plan Maker", "项目初始化助手")
    ]
    lines: list[str] = []
    for a in others:
        aid = a.get("id", "")
        role = a.get("role", "")
        goal = (a.get("goal") or "").split("\n")[0][:80]
        # Resolve tool names
        tool_ids_raw = a.get("tool_ids") or "[]"
        try:
            tool_ids = json.loads(tool_ids_raw) if isinstance(tool_ids_raw, str) else tool_ids_raw
        except (json.JSONDecodeError, TypeError):
            tool_ids = []
        tool_names: list[str] = []
        for tid in tool_ids[:12]:  # cap to keep prompt small
            tr = await crud.get_by_id("tools", tid)
            if tr:
                tool_names.append(tr.get("name", ""))
        lines.append(
            f"- {aid} | {role} — {goal}\n  工具: {', '.join(tool_names) or '(无)'}"
        )
    return "\n".join(lines) if lines else "（无可用 agent）"


def _assemble_draft_blueprint(session_id: str) -> dict:
    """Combine all phase outputs into the final draft blueprint shape
    that the frontend's blueprint editor consumes + persist_svc writes."""
    pathed_tasks: list[dict] = planner_cache_svc.get_phase_output(
        session_id, "project_mgmt",
    ) or []
    assignments: list[dict] = planner_cache_svc.get_phase_output(
        session_id, "agent_assignment",
    ) or []
    concept: dict | None = planner_cache_svc.get_phase_output(session_id, "concept")

    # Merge agent_id from assignments into the tasks
    assignment_by_idx = {a["task_index"]: a for a in assignments}
    final_tasks = []
    for i, t in enumerate(pathed_tasks):
        merged = dict(t)
        if i in assignment_by_idx:
            merged["agent_id"] = assignment_by_idx[i]["agent_id"]
        # Setup task already has agent_id from Phase 4
        final_tasks.append(merged)

    title = (concept or {}).get("title") if isinstance(concept, dict) else None
    overview_parts: list[str] = []
    if isinstance(concept, dict):
        overview_parts.append(f"# {concept.get('title', '项目')}")
        overview_parts.append("")
        overview_parts.append("## 核心循环")
        overview_parts.append(concept.get("core_loop", ""))
        overview_parts.append("")
        overview_parts.append("## 系统")
        for s in concept.get("systems", []):
            overview_parts.append(f"- {s}")
        overview_parts.append("")
        overview_parts.append("## 机制")
        for m in concept.get("mechanics", []):
            overview_parts.append(f"- {m}")
        overview_parts.append("")
        overview_parts.append(f"## 美术风格\n{concept.get('art_style', '')}")
        overview_parts.append("")
        overview_parts.append(f"## 目标玩家\n{concept.get('target_player', '')}")

    return {
        "name": title or "未命名项目",
        "execution_kind": "crew",
        "architecture_overview": "\n".join(overview_parts) or "（无概念文档）",
        "tasks": final_tasks,
    }


__all__ = ["run_crew"]
