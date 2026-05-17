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
    PHASE_CC_GOAL,
    PHASE_CC_ROLE,
    phase4_backstory,
    phase5_backstory,
    phase_cc_backstory,
)
from agents.sub_agents._list_performers_tool import (
    make_list_performers_tool,
)
from agents.sub_agents._planner_tools import (
    make_submit_assignments_tool,
    make_submit_atomic_tasks_tool,
    make_submit_code_contracts_tool,
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


PHASES = (
    "concept",
    "system_design",
    "review",
    "project_mgmt",
    "code_contract",      # PM v5: 代码契约设计师 (between Phase 4 and assignment)
    "agent_assignment",
)


# Hardcoded per-phase thinking defaults. Only Phase 1 (concept) is on —
# it emits long-form narrative concept doc and benefits from extended
# thinking. The other five phases must call a strict-schema submit tool;
# thinking forces temperature=1.0 + eats budget on Anthropic, which has
# been observed to make the agent fail to call the submit tool at all
# (`未捕获到合法输出，焦点修复中…`). Always gated by the pro model's
# cached supports_thinking — unsupported models stay off regardless.
PHASE_THINKING_DEFAULTS: dict[str, bool] = {
    "concept": True,
    "system_design": False,
    "review": False,
    "project_mgmt": False,
    "code_contract": False,
    "agent_assignment": False,
}


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

    # Session-level thinking toggle (set by the user in the Plan Maker
    # entry). Only takes effect when the resolved pro model's cached
    # supports_thinking is true — otherwise we silently drop it so a
    # stale toggle on an old session can't crash a non-reasoning model
    # request. The cheap binary classifier always runs without thinking.
    thinking_mode = bool(session.get("thinking_mode", 0))
    pro_supports_thinking = False
    if thinking_mode:
        pro_models = await crud.get_all(
            "llm_models",
            "provider_id = ? AND model_name = ?",
            (pro_provider["id"], pro_model),
        )
        pro_supports_thinking = (
            bool(pro_models[0].get("supports_thinking", 0)) if pro_models else False
        )

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
                thinking_mode=thinking_mode,
                supports_thinking=pro_supports_thinking,
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
            pool_summary = await _render_pool_summary()
            atomic_dict = await _run_phase(
                session_id=session_id,
                phase="system_design",
                role=PHASE2_ROLE, goal=PHASE2_GOAL,
                backstory=f"{PHASE2_BACKSTORY}\n\n# 下游 performer 池（拆任务时按这些能力单元的粒度切）\n{pool_summary}",
                description=phase2_input,
                expected_output="调一次 submit_atomic_tasks 提交任务列表后一句中文确认。",
                tools=[make_submit_atomic_tasks_tool(session_id)],
                provider=pro_provider, model_name=pro_model,
                temperature=0.5, max_tokens=4000,
                thinking_mode=thinking_mode,
                supports_thinking=pro_supports_thinking,
            )
            planner_cache_svc.set_phase_output(session_id, "system_design", atomic_dict["tasks"])
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 3: 审核策划 ──────────────────────────────────────
        if _need_run("review", start_from) and not _has_phase_output(session_id, "review"):
            planner_cache_svc.update(session_id, current_phase="review")
            atomic_tasks = planner_cache_svc.get_phase_output(session_id, "system_design")
            pool_summary = await _render_pool_summary()
            reviewed_dict = await _run_phase(
                session_id=session_id,
                phase="review",
                role=PHASE3_ROLE, goal=PHASE3_GOAL,
                backstory=f"{PHASE3_BACKSTORY}\n\n# 下游 performer 池（output_schema 要跟 Crew 的 QA 验收口径对齐）\n{pool_summary}",
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
                thinking_mode=thinking_mode,
                supports_thinking=pro_supports_thinking,
            )
            planner_cache_svc.set_phase_output(session_id, "review", reviewed_dict["tasks"])
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 4: 项目管理 ──────────────────────────────────────
        # v3.1 重设计：LLM 只发 path_specs + setup.extra_folders，
        # Python 代码做所有结构变换（插 setup task / 加 deps=[0] /
        # merge ReviewedTask 字段）。详见 _assemble_pathed_tasks 注释。
        if _need_run("project_mgmt", start_from) and not _has_phase_output(session_id, "project_mgmt"):
            planner_cache_svc.update(session_id, current_phase="project_mgmt")
            reviewed = planner_cache_svc.get_phase_output(session_id, "review")
            template_ctx = await _render_template_ctx(session)
            initializer_id = await _get_initializer_agent_id()
            allowed_prefixes = _extract_template_prefixes(template_ctx)
            phase4_dict = await _run_phase_with_validation(
                session_id=session_id,
                phase="project_mgmt",
                role=PHASE4_ROLE, goal=PHASE4_GOAL,
                backstory=phase4_backstory(template_ctx, initializer_id),
                description=(
                    "# 上游审核后的任务列表（Phase 3 产物）\n"
                    "```json\n"
                    f"{json.dumps(reviewed, ensure_ascii=False, indent=2)}\n"
                    "```\n\n"
                    f"总共 {len(reviewed or [])} 个上游任务，path_specs 必须 "
                    f"对应 {len(reviewed or [])} 条（每条一个 task_index 从 0 到 "
                    f"{len(reviewed or []) - 1}）。"
                ),
                expected_output=(
                    f"调一次 submit_pathed_tasks，path_specs 覆盖 "
                    f"{len(reviewed or [])} 个上游任务，然后一句中文确认。"
                ),
                tools=[make_submit_pathed_tasks_tool(session_id)],
                provider=pro_provider, model_name=pro_model,
                temperature=0.3, max_tokens=3000,
                thinking_mode=thinking_mode,
                supports_thinking=pro_supports_thinking,
                validator=lambda payload: _validate_path_specs(
                    payload, reviewed or [], allowed_prefixes,
                ),
            )
            # 组装最终 PathedTask 列表（含 setup + deps 调整）
            pathed_tasks = _assemble_pathed_tasks(
                reviewed=reviewed or [],
                path_specs=phase4_dict["path_specs"],
                setup_spec=phase4_dict["setup"],
                initializer_agent_id=initializer_id,
            )
            planner_cache_svc.set_phase_output(session_id, "project_mgmt", pathed_tasks)
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 5 (PM v5): 代码契约设计师 ────────────────────────
        # Decides the public-symbol contract for every task that
        # produces .cs files BEFORE Crews run. Crew Head cannot mutate
        # the contract; Crew QA verifies regex-match against generated
        # .cs and fails the task if any contract'd symbol is missing.
        # Non-code tasks (PNG / wav / prefab) get null contracts.
        if _need_run("code_contract", start_from) and not _has_phase_output(session_id, "code_contract"):
            planner_cache_svc.update(session_id, current_phase="code_contract")
            pathed = planner_cache_svc.get_phase_output(session_id, "project_mgmt")
            # Use _run_phase_with_validation (not _run_phase): we need the
            # post-Pydantic cross-task validator to reject contracts whose
            # imports point at non-existent symbols. _run_phase doesn't
            # have a `validator` kwarg.
            #
            # 2026-05-17 fix: the previous version dumped the FULL pathed
            # task list (detail / acceptance_notes / kind / deps / ...) and
            # capped max_tokens at 4000. For a 10-task project the output
            # alone (contracts array with files / exports / imports for
            # each .cs task) easily exceeds 4000 tokens — CrewAI then
            # ran into truncated JSON, exhausted max_iter, and
            # force_final_answer returned empty → "Invalid response from
            # LLM call - None or empty". Slim the input to ONLY the
            # fields code_contract needs to decide (task_index, title,
            # output_paths) and bump max_tokens to 16000.
            cc_pathed_slim = [
                {
                    "task_index": i,
                    "title": (t.get("title") or "")[:80],
                    "output_paths": t.get("output_paths") or [],
                    "kind": t.get("kind") or "regular",
                }
                for i, t in enumerate(pathed or [])
            ]
            cc_dict = await _run_phase_with_validation(
                session_id=session_id,
                phase="code_contract",
                role=PHASE_CC_ROLE, goal=PHASE_CC_GOAL,
                backstory=phase_cc_backstory(),
                description=(
                    "# 上游任务清单（精简版：仅 task_index + title + output_paths + kind）\n"
                    "```json\n"
                    f"{json.dumps(cc_pathed_slim, ensure_ascii=False, indent=2)}\n"
                    "```\n\n"
                    f"上游共 {len(pathed or [])} 个 task。逐个判断："
                    "output_paths 含 .cs → 需要 code_contract；全是非代码资产 → "
                    "code_contract 填 null。contracts 数组长度必须 == "
                    f"{len(pathed or [])}，task_index 必须覆盖 0..{len(pathed or []) - 1}。"
                ),
                expected_output=(
                    "调一次 submit_code_contracts，覆盖全部 task；然后一句中文确认。"
                ),
                tools=[make_submit_code_contracts_tool(session_id)],
                provider=pro_provider, model_name=pro_model,
                temperature=0.25, max_tokens=16000,
                thinking_mode=thinking_mode,
                supports_thinking=pro_supports_thinking,
                validator=lambda payload: _validate_code_contracts(
                    payload, pathed or [],
                ),
            )
            planner_cache_svc.set_phase_output(
                session_id, "code_contract",
                cc_dict.get("contracts", []),
            )
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 6 (renumbered, internal key unchanged): Agent 指挥员 ─
        # Phase 5 LLM picks each task's performer from the live pool that
        # list_performers exposes. It is *required* to call list_performers
        # before submit_assignments — submit_assignments now has zero
        # facility for new-agent creation, and an id outside the pool
        # is rejected post-LLM by _validate_assignments below.
        if _need_run("agent_assignment", start_from) and not _has_phase_output(session_id, "agent_assignment"):
            planner_cache_svc.update(session_id, current_phase="agent_assignment")
            pathed = planner_cache_svc.get_phase_output(session_id, "project_mgmt")
            assignments_dict = await _run_phase(
                session_id=session_id,
                phase="agent_assignment",
                role=PHASE5_ROLE, goal=PHASE5_GOAL,
                backstory=phase5_backstory(),
                description=(
                    "# 上游带路径的任务列表（Phase 4 产物）\n"
                    "```json\n"
                    f"{json.dumps(pathed, ensure_ascii=False, indent=2)}\n"
                    "```\n\n"
                    "**先调 list_performers(kind='all') 拿到真实可用 performer 池**，"
                    "再跳过 tasks[0] 的 setup（已 pre-assigned），给其余每个任务匹配 "
                    "performer_ref（kind + id），最后调 submit_assignments。"
                ),
                expected_output=(
                    "1) 一次 list_performers 调用 2) 一次 submit_assignments 调用 3) 一句中文确认。"
                ),
                tools=[
                    make_list_performers_tool(),
                    make_submit_assignments_tool(session_id),
                ],
                provider=pro_provider, model_name=pro_model,
                temperature=0.2, max_tokens=3000,
                thinking_mode=thinking_mode,
                supports_thinking=pro_supports_thinking,
            )
            raw_assignments = assignments_dict.get("assignments", [])
            validated = await _validate_assignments(raw_assignments, pathed or [])
            planner_cache_svc.set_phase_output(session_id, "agent_assignment", validated)

        # ── Assemble final draft blueprint ────────────────────────
        draft_blueprint = _assemble_draft_blueprint(session_id)
        planner_cache_svc.update(
            session_id,
            status="ready",
            current_phase="complete",
            draft_blueprint=draft_blueprint,
        )
        await _broadcast(session_id, "complete", "PM 工作流",
                         "phase_completed", "全部 6 个 phase 完成，草稿已就绪")
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
    thinking_mode: bool = False,
    supports_thinking: bool = False,
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
            thinking_mode=thinking_mode, supports_thinking=supports_thinking,
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
            thinking_mode=thinking_mode, supports_thinking=supports_thinking,
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


# ── Phase 4 specific: run + validator-driven retry ──────────────────


async def _run_phase_with_validation(
    *,
    session_id: str,
    phase: str,
    role: str, goal: str, backstory: str,
    description: str, expected_output: str,
    tools: list,
    provider: dict, model_name: str,
    temperature: float, max_tokens: int,
    validator,  # Callable[[dict], list[str]] — returns error strings; empty = OK
    thinking_mode: bool = False,
    supports_thinking: bool = False,
) -> dict:
    """Like _run_phase, but after a kickoff produces a captured payload
    we run a custom validator (e.g. coverage/conflict checks). On
    validation failure we *also* try a focused-repair kickoff that
    includes the validator errors in the prompt so the LLM can self-fix.

    This is what makes Plan A safe: Pydantic only verifies per-record
    structure; this layer enforces cross-record invariants (coverage,
    no duplicate indices, no path conflicts, prefix correctness)."""
    from src.tools.builtin.local._output_capture import pop_planner_output

    await _broadcast(session_id, phase, role, "started", f"phase {phase} started")

    last_validator_errors: list[str] = []

    # Try 1: standard kickoff
    try:
        await run_crewai_agent(
            session_id=session_id, role=role, goal=goal, backstory=backstory,
            description=description, expected_output=expected_output,
            tools=tools, provider=provider, model_name=model_name,
            max_iter=5, temperature=temperature, max_tokens=max_tokens,
            thinking_mode=thinking_mode, supports_thinking=supports_thinking,
            broadcast_steps=False,
        )
    except Exception as exc:  # noqa: BLE001
        await _broadcast(session_id, phase, role, "phase_failed",
                         f"kickoff 异常：{exc}", error=str(exc))
        raise

    payload = pop_planner_output(session_id, phase)
    if payload is not None:
        last_validator_errors = validator(payload)
        if not last_validator_errors:
            await _broadcast(session_id, phase, role, "phase_completed",
                             f"phase {phase} completed",
                             payload_preview=payload)
            return payload
        await _broadcast(
            session_id, phase, role, "retry",
            f"输出通过 Pydantic 但跨记录校验失败：{'; '.join(last_validator_errors[:3])}",
        )
    else:
        await _broadcast(session_id, phase, role, "retry",
                         "未捕获到合法输出，焦点修复中…")

    # Try 2: focused repair — include validator errors so LLM can fix
    error_hint = (
        f"# 上次失败原因\n你上次的 submit_pathed_tasks 调用没通过校验：\n"
        f"  - {chr(10) + '  - '.join(last_validator_errors)}\n"
        f"请这次**严格按上面的错误说明**修正后再调一次。"
        if last_validator_errors
        else "# 上次失败原因\n你没成功调用 submit_pathed_tasks。请这次"
              "**务必调用** submit_pathed_tasks 工具一次性提交。"
    )
    repair_desc = f"{description}\n\n{error_hint}"
    try:
        await run_crewai_agent(
            session_id=session_id, role=role, goal=goal, backstory=backstory,
            description=repair_desc, expected_output=expected_output,
            tools=tools, provider=provider, model_name=model_name,
            max_iter=3, temperature=temperature, max_tokens=max_tokens,
            thinking_mode=thinking_mode, supports_thinking=supports_thinking,
            broadcast_steps=False,
        )
    except Exception as exc:  # noqa: BLE001
        await _broadcast(session_id, phase, role, "phase_failed",
                         f"焦点修复异常：{exc}", error=str(exc))
        raise

    payload = pop_planner_output(session_id, phase)
    if payload is not None:
        last_validator_errors = validator(payload)
        if not last_validator_errors:
            await _broadcast(session_id, phase, role, "phase_completed",
                             f"phase {phase} completed (repaired)",
                             payload_preview=payload)
            return payload
        msg = ("phase project_mgmt 焦点修复后仍未通过校验："
               + "; ".join(last_validator_errors[:5]))
    else:
        msg = "phase project_mgmt: agent 未能成功调用提交工具（max_iter + 焦点修复均失败）"

    await _broadcast(session_id, phase, role, "phase_failed", msg, error=msg)
    raise RuntimeError(msg)


# ── Phase 4 cross-record validation + composition ───────────────────


def _validate_path_specs(
    payload: dict,
    reviewed_tasks: list[dict],
    allowed_prefixes: list[str],
) -> list[str]:
    """4 invariants that Pydantic can't check on its own:
        1. path_specs covers all upstream tasks (count + indices)
        2. no duplicate task_index
        3. paths use allowed template prefixes
        4. no path collides across tasks

    Returns list of error strings; empty list = valid."""
    errors: list[str] = []
    path_specs = payload.get("path_specs", [])
    n = len(reviewed_tasks)

    indices = [ps.get("task_index") for ps in path_specs]
    # 1. coverage
    expected = set(range(n))
    got = set(i for i in indices if isinstance(i, int))
    missing = sorted(expected - got)
    extra = sorted(got - expected)
    if missing:
        errors.append(f"path_specs 漏掉了上游任务索引：{missing}")
    if extra:
        errors.append(f"path_specs 含越界索引（上游只有 {n} 个任务）：{extra}")

    # 2. dup
    seen: dict[int, int] = {}
    for i in indices:
        if isinstance(i, int):
            seen[i] = seen.get(i, 0) + 1
    dups = [i for i, c in seen.items() if c > 1]
    if dups:
        errors.append(f"path_specs 含重复 task_index：{dups}")

    # 3. prefix correctness
    bad_prefix: list[str] = []
    for ps in path_specs:
        for p in (ps.get("output_paths") or []):
            if not any(p.startswith(prefix) for prefix in allowed_prefixes):
                bad_prefix.append(p)
    if bad_prefix:
        errors.append(
            f"以下路径不在模板允许的前缀下（{allowed_prefixes[:5]}…）："
            f"{bad_prefix[:5]}"
        )

    # 4. path collision across tasks
    all_paths: list[str] = []
    for ps in path_specs:
        all_paths.extend(ps.get("output_paths") or [])
    dup_paths = [p for p in set(all_paths) if all_paths.count(p) > 1]
    if dup_paths:
        errors.append(f"以下路径被多个任务共用（必须唯一）：{dup_paths[:5]}")

    return errors


def _validate_code_contracts(
    payload: dict,
    pathed_tasks: list[dict],
) -> list[str]:
    """V5 cross-record validation for Phase 5 code_contract output.

    Beyond Pydantic field-level checks, verify:
        1. Coverage: contracts length == pathed_tasks length; indices
           cover 0..N-1 exactly once.
        2. Type-correctness: a task's contract must be null iff its
           output_paths contains zero .cs files. Mismatch in either
           direction is wrong (forgot a code task / wrote a contract
           for an asset task).
        3. Path alignment: every contract.files[i].path must appear in
           that task's output_paths (no new files, no missing files).
        4. Cross-task symbol resolution: every imports.uses[k] must
           match some export.signature inside the from_task_index'd
           task's contract — short-name match, e.g.
           "PlayerController.OnDeath" resolves to a class export named
           PlayerController containing an event export named OnDeath.

    Errors are returned as plain strings the LLM can read and self-
    correct against (Layer 2 focused repair will include them in the
    prompt).
    """
    errors: list[str] = []
    contracts = payload.get("contracts") or []
    n = len(pathed_tasks)

    # 1. coverage
    indices = [c.get("task_index") for c in contracts]
    expected = set(range(n))
    got = {i for i in indices if isinstance(i, int)}
    missing = sorted(expected - got)
    extra = sorted(got - expected)
    if missing:
        errors.append(f"contracts 漏掉了 task_index：{missing}")
    if extra:
        errors.append(f"contracts 含越界 task_index（上游 {n} 个任务）：{extra}")
    dup_counts: dict[int, int] = {}
    for i in indices:
        if isinstance(i, int):
            dup_counts[i] = dup_counts.get(i, 0) + 1
    dups = [i for i, c in dup_counts.items() if c > 1]
    if dups:
        errors.append(f"contracts 含重复 task_index：{dups}")
    if errors:
        return errors  # Early-out — further checks need clean indexing

    # Build index → (task, contract) map for O(1) lookups
    by_idx: dict[int, tuple[dict, dict | None]] = {}
    for c in contracts:
        idx = c["task_index"]
        if 0 <= idx < n:
            by_idx[idx] = (pathed_tasks[idx], c.get("code_contract"))

    # 2. type-correctness: contract presence vs .cs presence
    for idx, (task, contract) in by_idx.items():
        output_paths = task.get("output_paths") or []
        has_cs = any(
            isinstance(p, str) and p.lower().endswith(".cs")
            for p in output_paths
        )
        if has_cs and contract is None:
            errors.append(
                f"task_index={idx} 的 output_paths 含 .cs 文件但 contract 为 null —— "
                "必须为产 .cs 的 task 写 contract"
            )
        elif not has_cs and contract is not None:
            errors.append(
                f"task_index={idx} 的 output_paths 没有 .cs 文件但写了 contract —— "
                "请把 code_contract 改为 null"
            )

    # 3. path alignment
    for idx, (task, contract) in by_idx.items():
        if not contract:
            continue
        cs_paths_in_task = {
            p for p in (task.get("output_paths") or [])
            if isinstance(p, str) and p.lower().endswith(".cs")
        }
        contract_paths = {
            f.get("path", "") for f in (contract.get("files") or [])
        }
        unknown = contract_paths - cs_paths_in_task
        forgotten = cs_paths_in_task - contract_paths
        if unknown:
            errors.append(
                f"task_index={idx} contract.files 含 task.output_paths 没列的路径："
                f"{sorted(unknown)[:5]}"
            )
        if forgotten:
            errors.append(
                f"task_index={idx} task.output_paths 有 .cs 但 contract.files 没覆盖："
                f"{sorted(forgotten)[:5]}"
            )

    # 4. cross-task symbol resolution
    # Build exports index: task_idx → set[short_symbol_names]
    # Short symbol name for a class export = class name from signature
    # For a method/event/field on a class file, short name = ClassName.MemberName
    exports_index: dict[int, set[str]] = {}
    for idx, (_task, contract) in by_idx.items():
        if not contract:
            continue
        names: set[str] = set()
        for f in contract.get("files") or []:
            # find the class name within this file (first class-kind export)
            class_name: str | None = None
            for exp in f.get("exports") or []:
                if exp.get("kind") in ("class", "interface", "struct", "enum"):
                    class_name = _extract_type_name(exp.get("signature", ""))
                    if class_name:
                        names.add(class_name)
                        break
            for exp in f.get("exports") or []:
                kind = exp.get("kind")
                sig = exp.get("signature", "")
                if kind in ("class", "interface", "struct", "enum"):
                    continue  # already added
                member = _extract_member_name(sig)
                if member and class_name:
                    names.add(f"{class_name}.{member}")
        exports_index[idx] = names

    for idx, (_task, contract) in by_idx.items():
        if not contract:
            continue
        for imp in contract.get("imports") or []:
            from_idx = imp.get("from_task_index")
            uses = imp.get("uses") or []
            if not isinstance(from_idx, int) or not (0 <= from_idx < n):
                errors.append(
                    f"task_index={idx} 的 import.from_task_index={from_idx!r} 越界"
                )
                continue
            available = exports_index.get(from_idx, set())
            for sym in uses:
                if sym not in available:
                    errors.append(
                        f"task_index={idx} 引用 task_index={from_idx} 的 `{sym}`，"
                        f"但 {from_idx} 没声明这个符号"
                        f"（exports 实际有：{sorted(available)[:8]}）"
                    )

    return errors


def _extract_type_name(signature: str) -> str | None:
    """从 'public class Foo : Bar' 抽 'Foo'；'public interface IBaz' → 'IBaz'。
    单行规范签名假设（v5 MVP 约束）。"""
    import re
    m = re.search(
        r"\b(?:class|interface|struct|enum)\s+(\w+)",
        signature,
    )
    return m.group(1) if m else None


def _extract_member_name(signature: str) -> str | None:
    """从成员签名抽短名：
       'public void Move(Vector2 d)'    → 'Move'
       'public event Action OnDeath'    → 'OnDeath'
       'public Transform CachedTransform' → 'CachedTransform'
       'public int Health { get; set; }' → 'Health'
    """
    import re
    # method:   public <RET> <NAME>(
    m = re.search(r"\b\w[\w<>,\s]*\s+(\w+)\s*\(", signature)
    if m:
        return m.group(1)
    # event:    public event <TYPE> <NAME>(...) | <NAME>;? | <NAME>$
    m = re.search(r"\bevent\s+\S+\s+(\w+)", signature)
    if m:
        return m.group(1)
    # property: public <TYPE> <NAME> { ... }
    m = re.search(r"\b\w+\s+(\w+)\s*\{", signature)
    if m:
        return m.group(1)
    # field:    public <TYPE> <NAME>;?  (trailing word)
    m = re.search(r"\b(\w+)\s*;?\s*$", signature.strip())
    if m:
        return m.group(1)
    return None


def _assemble_pathed_tasks(
    reviewed: list[dict],
    path_specs: list[dict],
    setup_spec: dict,
    initializer_agent_id: str,
) -> list[dict]:
    """Compose the final PathedTask list from LLM's per-task path
    delta + the upstream ReviewedTask records. Deterministic — same
    inputs always produce the same output."""
    # Index path_specs for O(1) lookup
    specs_by_idx = {ps["task_index"]: ps for ps in path_specs}

    # Build the regular/final_qa tasks: merge ReviewedTask + output_paths
    composed: list[dict] = []
    all_output_paths: list[str] = []
    for i, rt in enumerate(reviewed):
        spec = specs_by_idx.get(i, {})
        paths = list(spec.get("output_paths") or [])
        all_output_paths.extend(paths)
        composed.append({
            **rt,
            "output_paths": paths,
            "agent_id": None,  # Phase 5 will fill
        })

    # Setup task — derive folders from all output_paths' parents + extras.
    # Setup goes at index 0; recompute every other task's deps to +1 and
    # add 0 (since old indices shift).
    parent_dirs: set[str] = set()
    for p in all_output_paths:
        # Take parent if it's a file path (has extension); take itself if
        # it's already a dir-like path (ends with /)
        if "/" in p:
            parent = p.rsplit("/", 1)[0] + "/"
            parent_dirs.add(parent)
    for f in (setup_spec.get("extra_folders") or []):
        if f and not f.endswith("/"):
            f = f + "/"
        if f:
            parent_dirs.add(f)
    setup_folders = sorted(parent_dirs)

    setup_task = {
        "title": "创建项目目录结构",
        "detail": (
            "为后续任务批量创建子目录，避免后续 mkdir 缺失父目录。"
            "目录列表：" + ", ".join(setup_folders)
        ),
        "deps": [],
        "kind": "setup",
        "est_complexity": "small",
        "acceptance_notes": "所有列出的目录在文件系统上都被建好（mkdir -p 幂等）。",
        "input_sources": ["项目模板目录骨架 + 后续任务的 output_paths"],
        "output_schema": {
            "type": "object",
            "properties": {
                "file_paths": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": ["file_paths"],
        },
        "output_paths": setup_folders,
        "agent_id": initializer_agent_id,
    }

    # Reindex: setup is the new tasks[0]. Every previous index i becomes
    # i+1, and its deps' old indices [a, b, ...] become [a+1, b+1, ...] + [0]
    reindexed: list[dict] = []
    for rt in composed:
        new_deps = [d + 1 for d in (rt.get("deps") or [])]
        if 0 not in new_deps:
            new_deps.insert(0, 0)
        reindexed.append({**rt, "deps": new_deps})

    return [setup_task] + reindexed


def _extract_template_prefixes(template_context: str) -> list[str]:
    """Parse the rendered template context to find directory prefixes
    the LLM is allowed to use. The template renderer emits lines like:
        - Assets/Scripts/         # 推荐：核心系统与控制器
    so we grep for those bullets and take everything before the first
    space/comment."""
    prefixes: list[str] = []
    for line in template_context.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        rest = line[2:].strip()
        # Stop at first '#' or space
        for sep in ["#", " ", "  "]:
            idx = rest.find(sep)
            if idx > 0:
                rest = rest[:idx]
                break
        rest = rest.strip()
        if rest and rest not in prefixes:
            prefixes.append(rest)
    # Always allow these — Unity convention regardless of template
    for default in ("Assets/", "Packages/", "ProjectSettings/"):
        if default not in prefixes:
            prefixes.append(default)
    return prefixes


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
    # 2026-05-17: added 'code_contract' (PM v5) between project_mgmt
    # and agent_assignment. Forgetting to update this list breaks
    # 「从断点重来」 with a confusing "'code_contract' is not in list"
    # error — the restart endpoint passes start_from='code_contract'
    # but the resume gate couldn't locate it in the phase order.
    all_phases = ["completeness", "concept", "system_design", "review",
                  "project_mgmt", "code_contract", "agent_assignment"]
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


async def _render_pool_summary() -> str:
    """Compact human-readable summary of the performer pool. Used by
    Phase 2/3 backstories so they know the executor granularity."""
    from agents.sub_agents._list_performers_tool import (
        render_performer_pool_static_summary,
    )
    return await render_performer_pool_static_summary()


async def _validate_assignments(
    raw_assignments: list[dict],
    pathed_tasks: list[dict],
) -> list[dict]:
    """Cross-check each assignment's performer_ref against the live pool.

    Pydantic guards shape; this guards *existence*: even if the LLM
    invented an id that happens to look valid, we re-query the DB and
    reject anything that doesn't resolve. Returns the validated list
    (passes through unchanged on success) or raises a ValueError that
    the planner orchestrator surfaces to the user.

    2026-05-17 P0 override: tasks with kind='final_qa' must be assigned
    to the QA Engineer agent regardless of what the LLM picked. The
    魔塔副本 audit caught Phase 5 assigning Narrative Designer to
    final_qa because the task detail mentioned "产出质检报告" —
    sounds documentation-like, agent picked accordingly, but Narrative
    Designer has no QA tooling or QA prompt context and just wrote
    prose without running the actual checks. Hardcoded mapping is the
    only way to keep the final gate sane.
    """
    # Build the live id allow-list from the same source list_performers uses
    from agents.sub_agents._list_performers_tool import _build_payload
    pool = await _build_payload("all")
    agent_ids = {a["id"] for a in pool.get("agents", [])}
    crew_ids = {c["id"] for c in pool.get("crews", [])}

    # Find the QA Engineer agent id by querying the agents table
    # directly — _build_payload filters to _STANDALONE_AGENT_ROLES
    # (Narrative/Level/System Designer + Art Director) so the Phase 5
    # LLM doesn't see Crew-internal agents in its selection menu, but
    # the final_qa hard-override needs QA Engineer regardless. Direct
    # lookup keeps the LLM's pool clean and the override deterministic.
    qa_rows = await crud.get_all(
        "agents", "role = ?", ("QA Engineer",),
    )
    qa_agent_id: str | None = qa_rows[0]["id"] if qa_rows else None
    # Whitelist the QA Engineer's id for the existence check below so
    # the override doesn't fail validation against the filtered pool.
    if qa_agent_id:
        agent_ids = agent_ids | {qa_agent_id}

    bad: list[str] = []
    seen_indices: set[int] = set()
    setup_indices = {i for i, t in enumerate(pathed_tasks) if t.get("kind") == "setup"}
    final_qa_indices = {i for i, t in enumerate(pathed_tasks) if t.get("kind") == "final_qa"}

    for a in raw_assignments:
        idx = a.get("task_index")
        ref = a.get("performer_ref") or {}
        kind = ref.get("kind")
        pid = ref.get("id")
        if idx in setup_indices:
            bad.append(f"task_index={idx} 是 setup 任务，不允许分配 performer（已 pre-assigned）")
            continue
        if not isinstance(idx, int) or idx in seen_indices:
            bad.append(f"task_index={idx} 缺失或重复")
            continue
        seen_indices.add(idx)
        # Override before existence check — the LLM's pick is ignored
        # for final_qa, we slot the QA Engineer in.
        if idx in final_qa_indices:
            if not qa_agent_id:
                bad.append(
                    f"task_index={idx} 是 final_qa 任务，但 agent pool 中"
                    "找不到 role='QA Engineer' 的 agent（seed_crews 未跑？）"
                )
                continue
            a["performer_ref"] = {"kind": "agent", "id": qa_agent_id}
            kind = "agent"
            pid = qa_agent_id
            log.info("phase5.final_qa_overridden_to_qa_engineer",
                     task_index=idx, agent_id=qa_agent_id)
        if kind == "agent":
            if pid not in agent_ids:
                bad.append(f"task_index={idx}: agent id '{pid}' 不在可用池（list_performers 没列出）")
        elif kind == "crew":
            if pid not in crew_ids:
                bad.append(f"task_index={idx}: crew id '{pid}' 不在可用池")
        else:
            bad.append(f"task_index={idx}: performer_ref.kind 必须是 'agent' 或 'crew'，收到 '{kind}'")

    if bad:
        raise ValueError(
            "Phase 5 assignments validation failed:\n  - "
            + "\n  - ".join(bad)
        )
    return raw_assignments


def _assemble_draft_blueprint(session_id: str) -> dict:
    """Combine all phase outputs into the final draft blueprint shape
    that the frontend's blueprint editor consumes + persist_svc writes."""
    pathed_tasks: list[dict] = planner_cache_svc.get_phase_output(
        session_id, "project_mgmt",
    ) or []
    assignments: list[dict] = planner_cache_svc.get_phase_output(
        session_id, "agent_assignment",
    ) or []
    # PM v5: contracts are an N-element list aligned 1:1 with pathed_tasks
    # by task_index. Each entry's code_contract may be None (non-code task).
    code_contracts: list[dict] = planner_cache_svc.get_phase_output(
        session_id, "code_contract",
    ) or []
    concept: dict | None = planner_cache_svc.get_phase_output(session_id, "concept")

    # PM v4: assignments carry performer_ref={kind, id}. For 'agent' kind
    # we also stamp agent_id (legacy column) so workflow_svc fallbacks
    # and the team page still find a row. For 'crew' kind agent_id stays
    # null — workflow_svc._run_agent looks at performer_kind first.
    assignment_by_idx = {a["task_index"]: a for a in assignments}
    contract_by_idx = {c["task_index"]: c.get("code_contract") for c in code_contracts}
    final_tasks = []
    for i, t in enumerate(pathed_tasks):
        merged = dict(t)
        if i in assignment_by_idx:
            ref = assignment_by_idx[i].get("performer_ref") or {}
            kind = ref.get("kind")
            pid = ref.get("id")
            merged["performer_kind"] = kind
            merged["performer_id"] = pid
            if kind == "agent":
                merged["agent_id"] = pid
        # Setup task already has agent_id from Phase 4; also stamp it as
        # an "agent" performer so workflow_svc routes it correctly.
        elif t.get("agent_id"):
            merged["performer_kind"] = "agent"
            merged["performer_id"] = t["agent_id"]
        # PM v5: attach code_contract (may be None for non-code tasks).
        # Stored on merged['code_contract'] as a dict; persist_svc will
        # json.dumps when writing to the DB column.
        merged["code_contract"] = contract_by_idx.get(i)
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
