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
    PHASE7_GOAL,
    PHASE7_ROLE,
    PHASE_CC_GOAL,
    PHASE_CC_ROLE,
    phase4_backstory,
    phase5_backstory,
    phase7_backstory,
    phase_cc_backstory,
)
from agents.sub_agents._list_performers_tool import (
    make_list_performers_tool,
)
from agents.sub_agents._planner_tools import (
    make_submit_art_style_spec_tool,
    make_submit_assignments_tool,
    make_submit_atomic_tasks_tool,
    make_submit_code_contracts_tool,
    make_submit_code_contract_single_tool,
    make_submit_concept_tool,
    make_submit_pathed_tasks_tool,
    make_submit_path_spec_single_tool,
    make_submit_reviewed_tasks_tool,
    make_submit_reviewed_task_single_tool,
)
from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud
from services import planner_cache_svc
from src.tools.builtin.local._output_capture import (
    clear_planner_session,
    pop_planner_output,
    set_planner_output,
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


async def _resolve_flash_pair(session: dict) -> tuple[dict, str]:
    """Find the (provider_row, "deepseek-v4-flash") pair for PM Phase 2-6.

    DeepSeek v4-pro/reasoner does NOT accept strict tool_choice (4xx),
    so the forced-fallback path (Try-3) needs a chat-mode model. We
    pin to v4-flash by name. If the DB doesn't have a v4-flash row (or
    no DeepSeek provider at all), fall back to whatever pick_llm("cheap")
    resolves — at worst, user gets the same model they were already
    using session-wide.
    """
    rows = await crud.get_all(
        "llm_models", "LOWER(model_name) = ?", ("deepseek-v4-flash",),
    )
    if rows:
        provider_id = rows[0]["provider_id"]
        provider_rows = await crud.get_all(
            "llm_providers", "id = ?", (provider_id,),
        )
        if provider_rows:
            return dict(provider_rows[0]), "deepseek-v4-flash"
    # Fallback: cheap pick (should still be v4-flash for current users).
    log.warning("planner.flash_pair_fallback",
                hint="no deepseek-v4-flash row; using pick_llm(cheap)")
    return await pick_llm(session, "cheap")


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
        # PM v6 (2026-05-19): split model strategy.
        #   - Phase 1 (concept) uses pro (deepseek-v4-pro / reasoner) +
        #     thinking_mode — creative, simple submit schema, ReAct-auto
        #     tool_choice works fine.
        #   - Phase 2-6 use deepseek-v4-flash (chat mode) — they need
        #     the forced tool_choice fallback (Try-3), which DeepSeek
        #     reasoner does NOT support (4xx). Picking v4-pro for these
        #     phases is the root cause of the 2026-05-19 Phase-3 stall.
        pro_provider, pro_model = await pick_llm(session, "pro")
        cheap_provider, cheap_model = await pick_llm(session, "cheap")
        flash_provider, flash_model = await _resolve_flash_pair(session)
    except (ValueError, KeyError) as exc:
        planner_cache_svc.update(session_id, status="failed",
                                  error=f"LLM 配置错误：{exc}")
        return planner_cache_svc.get(session_id) or {}

    # Look up the pro model row once. We need two things from it:
    #   - supports_thinking — gates thinking on the per-phase defaults
    #     (PHASE_THINKING_DEFAULTS). An unsupported model silently
    #     downgrades to off so a stale config can't crash a request.
    #   - max_tokens — the model's declared output cap. We hand each
    #     phase 80% of that so even a 20-task review JSON has room
    #     (Phase 3 previously hardcoded 4000, which truncated and
    #     killed tool_use parsing → "未捕获到合法输出").
    # Session-level thinking_mode (DB column) is kept for backward
    # compatibility with old data but no longer consumed here — the
    # orchestrator now decides per-phase via PHASE_THINKING_DEFAULTS.
    pro_models = await crud.get_all(
        "llm_models",
        "provider_id = ? AND model_name = ?",
        (pro_provider["id"], pro_model),
    )
    pro_model_row = pro_models[0] if pro_models else {}
    pro_supports_thinking = bool(pro_model_row.get("supports_thinking", 0))
    # Floor at 4096 in case the DB row is missing/zero — Phase 3's
    # original 4000 was already too small, so 4096 is the minimum
    # we'd ever want to spend.
    pro_max_tokens = int(pro_model_row.get("max_tokens") or 8192)
    phase_max_tokens = max(4096, int(pro_max_tokens * 0.8))

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
                temperature=0.7, max_tokens=phase_max_tokens,
                thinking_mode=PHASE_THINKING_DEFAULTS["concept"],
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
                # PM v6: Phase 2 → flash (chat mode) — needs forced
                # tool_choice fallback which v4-pro/reasoner rejects.
                provider=flash_provider, model_name=flash_model,
                temperature=0.5, max_tokens=phase_max_tokens,
                thinking_mode=False,
                supports_thinking=False,
            )
            planner_cache_svc.set_phase_output(session_id, "system_design", atomic_dict["tasks"])
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 3: 审核策划 (PM v6 fan-out) ──────────────────────
        # Each task gets one independent forced-tool-call to v4-flash;
        # caller aggregates the N single-task results back into the
        # `{"tasks": [...]}` shape the downstream cache expects.
        if _need_run("review", start_from) and not _has_phase_output(session_id, "review"):
            planner_cache_svc.update(session_id, current_phase="review")
            atomic_tasks = planner_cache_svc.get_phase_output(session_id, "system_design") or []
            pool_summary = await _render_pool_summary()
            full_backstory_3 = (
                f"{PHASE3_BACKSTORY}\n\n"
                f"# 下游 performer 池（output_schema 要跟 Crew 的 QA 验收口径对齐）\n"
                f"{pool_summary}"
            )

            def _phase3_desc(i: int, t: dict) -> str:
                return (
                    f"# 你只为这一个 task 补完（不是全部）\n"
                    f"task_index = {i}\n\n"
                    f"原 task (Phase 2 产出):\n"
                    f"```json\n{json.dumps(t, ensure_ascii=False, indent=2)}\n```\n\n"
                    f"请保留原字段，并补完：\n"
                    f"- acceptance_notes: 验收说明\n"
                    f"- input_sources: 信息来源数组\n"
                    f"- output_schema: JSON Schema，必须含 file_paths 数组要求（除非 kind=final_qa）\n\n"
                    f"调一次 submit_reviewed_task_single 提交这一个完整的 ReviewedTask。"
                )

            await _broadcast(session_id, "review", PHASE3_ROLE,
                             "started", f"phase review started (fan-out × {len(atomic_tasks)})")
            results = await _run_phase_per_task(
                session_id=session_id,
                phase="review",
                role=PHASE3_ROLE,
                backstory=full_backstory_3,
                items=atomic_tasks,
                per_task_description_builder=_phase3_desc,
                submit_tool_factory=lambda: make_submit_reviewed_task_single_tool(session_id),
                provider=flash_provider, model_name=flash_model,
                concurrency=3,
                temperature=0.2,
                max_tokens=2048,
            )

            reviewed_tasks: list[dict] = []
            n_failed = 0
            for i, r in enumerate(results):
                if r is None or not isinstance(r.get("task"), dict):
                    n_failed += 1
                    # Surface failure but keep the original task minimally
                    # populated so downstream phases don't crash on a
                    # missing index. The user sees a fan-out warning.
                    fallback = dict(atomic_tasks[i])
                    fallback.setdefault("acceptance_notes",
                                        f"⚠ Phase 3 fan-out failed for task {i}; placeholder.")
                    fallback.setdefault("input_sources", [])
                    fallback.setdefault("output_schema", {
                        "type": "object",
                        "properties": {"file_paths": {"type": "array",
                                                       "items": {"type": "string"}}},
                        "required": ["file_paths"],
                    })
                    reviewed_tasks.append(fallback)
                else:
                    reviewed_tasks.append(r["task"])
            if n_failed > 0:
                await _broadcast(session_id, "review", PHASE3_ROLE,
                                 "warning",
                                 f"Phase 3 fan-out: {n_failed}/{len(atomic_tasks)} 个 task 未通过 — 用 placeholder 兜底")
            await _broadcast(session_id, "review", PHASE3_ROLE,
                             "phase_completed",
                             f"phase review completed (fan-out, {len(atomic_tasks) - n_failed}/{len(atomic_tasks)} ok)")
            planner_cache_svc.set_phase_output(session_id, "review", reviewed_tasks)
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 4: 项目管理 (PM v6 fan-out) ──────────────────────
        # Each task independently decides its own output_paths via a
        # single forced-tool-call. Python aggregates + dedups collisions
        # post-LLM (no need for the LLM to see other tasks' choices).
        # setup.extra_folders falls out of all paths' parent dirs.
        if _need_run("project_mgmt", start_from) and not _has_phase_output(session_id, "project_mgmt"):
            planner_cache_svc.update(session_id, current_phase="project_mgmt")
            reviewed = planner_cache_svc.get_phase_output(session_id, "review") or []
            template_ctx = await _render_template_ctx(session)
            initializer_id = await _get_initializer_agent_id()
            allowed_prefixes = _extract_template_prefixes(template_ctx)
            full_backstory_4 = phase4_backstory(template_ctx, initializer_id)

            def _phase4_desc(i: int, t: dict) -> str:
                return (
                    f"# 你只为这一个 task 决定 output_paths\n"
                    f"task_index = {i}\n\n"
                    f"task 资料:\n"
                    f"```json\n{json.dumps(t, ensure_ascii=False, indent=2)}\n```\n\n"
                    f"模板允许的目录前缀: {allowed_prefixes}\n"
                    f"output_paths 必须每条以一个允许前缀开头。\n\n"
                    f"调一次 submit_path_spec_single 提交单个 PathSpec："
                    f"`{{\"task_index\": {i}, \"output_paths\": [...]}}`。"
                )

            await _broadcast(session_id, "project_mgmt", PHASE4_ROLE,
                             "started", f"phase project_mgmt started (fan-out × {len(reviewed)})")
            results = await _run_phase_per_task(
                session_id=session_id,
                phase="project_mgmt",
                role=PHASE4_ROLE,
                backstory=full_backstory_4,
                items=reviewed,
                per_task_description_builder=_phase4_desc,
                submit_tool_factory=lambda: make_submit_path_spec_single_tool(session_id),
                provider=flash_provider, model_name=flash_model,
                concurrency=3,
                temperature=0.3,
                max_tokens=1024,
            )

            # Aggregate + dedup. Each result is {"path_spec": {task_index, output_paths}}.
            raw_path_specs: list[dict] = []
            for i, r in enumerate(results):
                if r is None or not isinstance(r.get("path_spec"), dict):
                    log.warning("planner.phase4.item_failed_using_placeholder",
                                session_id=session_id, task_index=i)
                    raw_path_specs.append({"task_index": i, "output_paths": []})
                else:
                    ps = dict(r["path_spec"])
                    ps.setdefault("task_index", i)
                    raw_path_specs.append(ps)
            deduped_specs, rename_log = _dedup_path_specs(raw_path_specs)
            for hint in rename_log:
                await _broadcast(session_id, "project_mgmt", PHASE4_ROLE,
                                 "warning", hint)
            cross_errors = _validate_path_specs(
                {"path_specs": deduped_specs},
                reviewed,
                allowed_prefixes,
            )
            # Filter out the coverage / count errors that fan-out can't
            # natively produce — only surface real prefix / collision
            # issues that survived dedup.
            real_errors = [e for e in cross_errors
                           if "path_specs 漏掉" not in e
                           and "path_specs 含越界" not in e
                           and "path_specs 含重复 task_index" not in e]
            for err in real_errors:
                await _broadcast(session_id, "project_mgmt", PHASE4_ROLE,
                                 "warning", err)
            await _broadcast(session_id, "project_mgmt", PHASE4_ROLE,
                             "phase_completed",
                             f"phase project_mgmt completed (fan-out, {len(deduped_specs)} specs)")

            # 组装最终 PathedTask 列表（含 setup + deps 调整）
            pathed_tasks = _assemble_pathed_tasks(
                reviewed=reviewed,
                path_specs=deduped_specs,
                setup_spec={"extra_folders": []},
                initializer_agent_id=initializer_id,
            )
            # 2026-05-19: detect "同质合并" — a single task that bundles
            # multiple homogeneous artifacts (≥2 .cs, ≥2 .png, ≥2 .wav,
            # ≥2 .prefab). These bundles are the #1 cause of Crew
            # Executor 超 max_iter（产出 2/5 文件就停手），should have
            # been split in Phase 2/3. Surface as warning so user sees
            # it in the planner log; flow proceeds because rejecting at
            # this stage would deadlock the planner (Phase 4 LLM can't
            # add new tasks itself).
            bundling_warnings = _detect_same_kind_bundling(pathed_tasks)
            for w in bundling_warnings:
                await _broadcast(session_id, "project_mgmt", PHASE4_ROLE,
                                 "warning", w)
                log.warning("planner.same_kind_bundling",
                            session_id=session_id, hint=w)
            planner_cache_svc.set_phase_output(session_id, "project_mgmt", pathed_tasks)
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 5 (PM v5): 代码契约设计师 ────────────────────────
        # Decides the public-symbol contract for every task that
        # produces .cs files BEFORE Crews run. Crew Head cannot mutate
        # the contract; Crew QA verifies regex-match against generated
        # .cs and fails the task if any contract'd symbol is missing.
        # Non-code tasks (PNG / wav / prefab) get null contracts.
        # ── Phase 5 (PM v6 fan-out): code_contract ─────────────────
        # Each task gets one forced-tool-call deciding its own contract
        # (or null for non-code tasks). cross-task `imports` validation
        # moves to Python post-processing as a non-blocking warning.
        if _need_run("code_contract", start_from) and not _has_phase_output(session_id, "code_contract"):
            planner_cache_svc.update(session_id, current_phase="code_contract")
            pathed = planner_cache_svc.get_phase_output(session_id, "project_mgmt") or []
            full_backstory_5 = phase_cc_backstory()

            # Slim list used in each per-task prompt so cross-task refs
            # in `imports` have context (the LLM needs to know other
            # tasks' exports to reference them).
            cc_pathed_slim = [
                {
                    "task_index": i,
                    "title": (t.get("title") or "")[:80],
                    "output_paths": t.get("output_paths") or [],
                    "kind": t.get("kind") or "regular",
                }
                for i, t in enumerate(pathed)
            ]

            def _phase5_desc(i: int, t: dict) -> str:
                paths = t.get("output_paths") or []
                has_cs = any(p.lower().endswith(".cs") for p in paths if isinstance(p, str))
                hint = (
                    "本 task output_paths 含 .cs → 必须写完整 code_contract"
                    if has_cs
                    else "本 task 不含 .cs → code_contract 填 null"
                )
                return (
                    f"# 你只为这一个 task 决定 code_contract\n"
                    f"task_index = {i}\n\n"
                    f"task 资料:\n"
                    f"```json\n{json.dumps(t, ensure_ascii=False, indent=2)}\n```\n\n"
                    f"## 上游 task 清单（仅供 imports 字段引用）\n"
                    f"```json\n{json.dumps(cc_pathed_slim, ensure_ascii=False, indent=2)}\n```\n\n"
                    f"判断规则：{hint}\n\n"
                    f"调一次 submit_code_contract_single 提交单个 TaskCodeContract："
                    f"`{{\"record\": {{\"task_index\": {i}, \"code_contract\": ... 或 null}}}}`。"
                )

            await _broadcast(session_id, "code_contract", PHASE_CC_ROLE,
                             "started", f"phase code_contract started (fan-out × {len(pathed)})")
            results = await _run_phase_per_task(
                session_id=session_id,
                phase="code_contract",
                role=PHASE_CC_ROLE,
                backstory=full_backstory_5,
                items=pathed,
                per_task_description_builder=_phase5_desc,
                submit_tool_factory=lambda: make_submit_code_contract_single_tool(session_id),
                provider=flash_provider, model_name=flash_model,
                concurrency=3,
                temperature=0.25,
                max_tokens=3072,
            )

            contracts: list[dict] = []
            n_failed = 0
            for i, r in enumerate(results):
                if r is None or not isinstance(r.get("record"), dict):
                    n_failed += 1
                    # null contract is a safe fallback — Crew QA / validators
                    # will pull a stronger contract via Debugger if needed.
                    contracts.append({"task_index": i, "code_contract": None})
                else:
                    rec = dict(r["record"])
                    rec.setdefault("task_index", i)
                    contracts.append(rec)
            # Cross-task imports check (warning only, never blocks).
            cc_warnings = _validate_code_contracts(
                {"contracts": contracts}, pathed,
            )
            real_cc_warnings = [w for w in cc_warnings
                                if "contracts 漏掉" not in w
                                and "contracts 含越界" not in w
                                and "contracts 含重复" not in w]
            for w in real_cc_warnings:
                await _broadcast(session_id, "code_contract", PHASE_CC_ROLE,
                                 "warning", w)
            if n_failed > 0:
                await _broadcast(session_id, "code_contract", PHASE_CC_ROLE,
                                 "warning",
                                 f"Phase 5 fan-out: {n_failed}/{len(pathed)} 个 task 未通过 — code_contract 兜底 null")
            await _broadcast(session_id, "code_contract", PHASE_CC_ROLE,
                             "phase_completed",
                             f"phase code_contract completed (fan-out, {len(pathed) - n_failed}/{len(pathed)} ok)")
            planner_cache_svc.set_phase_output(
                session_id, "code_contract", contracts,
            )
            if _check_cancelled(session_id):
                return planner_cache_svc.get(session_id) or {}

        # ── Phase 6: 指派 performer (PM v6 — 纯 Python 规则) ──────────
        # 2026-05-19 rewrite: dropped the LLM call. Routing-by-output_paths-
        # suffix is a pure rule (.cs → 系统实现组, .png → 2D 美术资产组,
        # .wav → 音频组, ...). LLM here added 30-90s + tokens + the
        # DeepSeek tool_choice "silently routed to reasoner" race, with
        # zero reasoning value. _assign_performers_by_rule does the
        # mapping in ~1ms; _validate_assignments still runs to verify
        # ids exist (and to apply the final_qa → QA Engineer override).
        if _need_run("agent_assignment", start_from) and not _has_phase_output(session_id, "agent_assignment"):
            planner_cache_svc.update(session_id, current_phase="agent_assignment")
            pathed = planner_cache_svc.get_phase_output(session_id, "project_mgmt") or []
            await _broadcast(session_id, "agent_assignment", PHASE5_ROLE,
                             "started", f"phase agent_assignment started (rule-based, {len(pathed)} tasks)")
            raw_assignments = await _assign_performers_by_rule(pathed)
            validated = await _validate_assignments(raw_assignments, pathed)
            await _broadcast(session_id, "agent_assignment", PHASE5_ROLE,
                             "phase_completed",
                             f"phase agent_assignment completed (rule-based, {len(validated)} assignments)")

            # Crew v5 (2026-05-19): group homogeneous Crew tasks into
            # parent crew_group + N children so the Crew's Head/QA only
            # run once and Executor fans out. Pure Python — LLM doesn't
            # decide. See _merge_into_crew_groups for the cluster rule.
            merged_pathed, merged_assignments = _merge_into_crew_groups(
                pathed or [], validated,
            )
            if len(merged_pathed) != len(pathed or []):
                log.info("planner.crew_groups_merged",
                         session_id=session_id,
                         original_count=len(pathed or []),
                         merged_count=len(merged_pathed),
                         new_parents=len(merged_pathed) - len(pathed or []))
                planner_cache_svc.set_phase_output(
                    session_id, "project_mgmt", merged_pathed,
                )
                validated = merged_assignments

            planner_cache_svc.set_phase_output(session_id, "agent_assignment", validated)

        # ── Phase 7: StyleArchitect (2026-05-20) ──────────────────
        # Project-level art style decision. Runs **once per project**
        # iff any task has an image output. Output is persisted to
        # `.mycrew_pending/art_style.json` and injected into the first
        # fanout step's head_spec on every art Crew run.
        if _need_run("art_style", start_from) and not _has_phase_output(session_id, "art_style"):
            pathed = planner_cache_svc.get_phase_output(session_id, "project_mgmt") or []
            if _project_has_art_tasks(pathed):
                planner_cache_svc.update(session_id, current_phase="art_style")
                concept = planner_cache_svc.get_phase_output(session_id, "concept")
                concept_block = (
                    f"\n```json\n{json.dumps(concept, ensure_ascii=False, indent=2)}\n```"
                    if isinstance(concept, dict) else "（PRD 直接走，没 ConceptDoc）"
                )
                await _broadcast(session_id, "art_style", PHASE7_ROLE,
                                 "started", "phase art_style started")
                try:
                    style_dict = await _run_phase(
                        session_id=session_id,
                        phase="art_style",
                        role=PHASE7_ROLE, goal=PHASE7_GOAL,
                        backstory=phase7_backstory(),
                        description=(
                            f"# 用户原始需求\n{user_message}\n\n"
                            f"# Phase 1 主策划 ConceptDoc\n{concept_block}\n\n"
                            f"# 任务\n基于上面两段信号，**只输出**项目级 ArtStyleSpec。"
                            f"调一次 submit_art_style_spec 提交完整数据。"
                        ),
                        expected_output="调一次 submit_art_style_spec 提交 ArtStyleSpec 后一句中文确认。",
                        tools=[make_submit_art_style_spec_tool(session_id)],
                        # flash + tool_choice forced — same model strategy as
                        # other small phases. ArtStyleSpec schema is shallow
                        # (6 fields) so flash handles it easily.
                        provider=flash_provider, model_name=flash_model,
                        temperature=0.5, max_tokens=2048,
                        thinking_mode=False,
                        supports_thinking=False,
                    )
                    spec = style_dict.get("spec") if isinstance(style_dict, dict) else None
                    if isinstance(spec, dict):
                        planner_cache_svc.set_phase_output(session_id, "art_style", spec)
                        await _broadcast(session_id, "art_style", PHASE7_ROLE,
                                         "phase_completed",
                                         f"phase art_style completed (background_mode={spec.get('background_mode')}, "
                                         f"checkpoint={spec.get('checkpoint')})")
                except Exception as exc:  # noqa: BLE001
                    log.warning("planner.phase7_failed",
                                session_id=session_id, error=str(exc))
                    await _broadcast(session_id, "art_style", PHASE7_ROLE,
                                     "phase_failed", f"phase art_style failed: {exc}",
                                     error=str(exc))
                    # Fail-open: art_style is best-effort. workflow_svc
                    # falls back to a default style if the file is
                    # missing — see _load_art_style_spec.
                if _check_cancelled(session_id):
                    return planner_cache_svc.get(session_id) or {}
            else:
                log.info("planner.phase7_skipped_no_art_tasks",
                         session_id=session_id)

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
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("planner.completeness_llm_failed",
                    session_id=session_id, error=str(exc))
        return "ONELINE"  # fail-open to ONELINE (safer)
    raw = (resp.text or "").strip().upper()
    return "PRD" if "PRD" in raw else "ONELINE"


def _inline_refs(schema: dict) -> dict:
    """Dereference Pydantic V2 JSON-Schema's `$defs` + `$ref` into a
    fully inlined schema.

    Pydantic emits `{"$ref": "#/$defs/Foo"}` + a `$defs` section, which
    follows JSON-Schema Draft 2020-12. DeepSeek's OpenAI-compat function-
    calling endpoint chokes on this — its parser wants a flat
    `parameters` schema. Without dereferencing, the LiteLLM call fails
    silently inside the Try-3 fallback. We expand every `$ref` in-place
    and drop the `$defs` wrapper.

    Cycle-safe via a visited set on the ref name. Returns a new dict; the
    input is not mutated.
    """
    import copy
    sch = copy.deepcopy(schema)
    defs = sch.pop("$defs", {}) or {}

    def _walk(node: Any, stack: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref[len("#/$defs/"):]
                if name in stack:
                    # Cycle — preserve the ref rather than infinite-loop.
                    return {"type": "object"}
                target = defs.get(name)
                if target is None:
                    return {"type": "object"}
                # Merge sibling fields on the $ref node (descriptions, etc.)
                merged = copy.deepcopy(target)
                for k, v in node.items():
                    if k != "$ref":
                        merged[k] = v
                return _walk(merged, stack + (name,))
            return {k: _walk(v, stack) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v, stack) for v in node]
        return node

    return _walk(sch, ())


# ── Try 3 fallback: force tool_choice via direct LiteLLM call ───────
#
# 2026-05-19 root cause: deepseek-flash inside CrewAI's ReAct loop
# routinely chooses to "summarise in markdown" instead of calling the
# submit_* tool — observed across Phase 2 / Phase 5 with identical input
# producing both pass and fail across consecutive runs (one in 145s,
# next in 45s). Adding max_iter doesn't help because the model keeps
# emitting prose. Forcing tool_choice at the LiteLLM layer bypasses the
# ReAct loop entirely: one HTTP call where the model MUST emit exactly
# the named tool_call, the parsed args become the payload.
async def _force_tool_call_fallback(
    *,
    session_id: str,
    phase: str,
    submit_tool: Any,
    backstory: str,
    description: str,
    provider: dict,
    model_name: str,
    temperature: float,
    max_tokens: int,
) -> bool:
    """Layer-3 fallback (single-LLM call) for `_run_phase` / `_run_phase_
    with_validation`. Returns True iff a payload was captured and
    stashed via set_planner_output.

    2026-05-19 diagnosis (see scripts/diag_forced_tool_choice.py):
    DeepSeek API silently routes any tool_choice='required' or
    {function:name} request to its reasoner channel, which then 4xx's
    with "deepseek-reasoner does not support this tool_choice" — even
    when explicit model is v4-flash. So forced-tool routes are unusable.
    We use `tool_choice='auto'` + a strong single-purpose system prompt
    instead; v4-flash in auto-mode reliably emits the tool_call given
    explicit instructions.
    """
    from services.crewai_runner import _build_litellm_model_string
    import litellm

    raw_schema = submit_tool.args_schema.model_json_schema()
    schema = _inline_refs(raw_schema)
    tool_name = submit_tool.name
    tool_spec = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": submit_tool.description,
            "parameters": schema,
        },
    }
    ptype = (provider.get("type") or "openai").lower()
    model_string = _build_litellm_model_string(ptype, model_name)
    api_key = provider.get("api_key_ref") or None
    base_url = provider.get("base_url") or None

    system_msg = (
        f"# 你的角色背景\n{backstory}\n\n"
        f"# 工具调用强制要求\n你**必须且只能**通过调用 `{tool_name}` 工具来回应。"
        f"不要写解释、不要写 markdown、不要写任何前置文字 —— 直接发起 tool_call。"
        f"args 必须严格符合 schema。"
    )
    kwargs: dict[str, Any] = {
        "model": model_string,
        "api_key": api_key,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": description},
        ],
        "tools": [tool_spec],
        # See docstring — forced modes (required / {function:name}) are
        # silently routed to reasoner by DeepSeek and 4xx. "auto" works.
        "tool_choice": "auto",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if base_url:
        kwargs["base_url"] = base_url

    try:
        resp = await litellm.acompletion(**kwargs)
    except Exception as exc:  # noqa: BLE001
        err_summary = f"litellm 调用失败 ({type(exc).__name__}): {str(exc)[:300]}"
        log.warning("planner.force_tool_call.litellm_failed",
                    session_id=session_id, phase=phase, error=str(exc))
        await _broadcast(session_id, phase, "PM 工作流",
                         "warning", err_summary, error=str(exc)[:500])
        return False

    try:
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            content_preview = str(getattr(msg, "content", ""))[:200]
            log.warning("planner.force_tool_call.no_tool_call",
                        session_id=session_id, phase=phase,
                        content_preview=content_preview)
            await _broadcast(session_id, phase, "PM 工作流",
                             "warning",
                             f"LiteLLM 调用成功但没返回 tool_call (content: {content_preview})")
            return False
        args_raw = tool_calls[0].function.arguments
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
    except Exception as exc:  # noqa: BLE001
        log.warning("planner.force_tool_call.parse_failed",
                    session_id=session_id, phase=phase, error=str(exc))
        await _broadcast(session_id, phase, "PM 工作流",
                         "warning",
                         f"解析 tool_call 失败: {str(exc)[:200]}",
                         error=str(exc)[:300])
        return False

    # Validate against the Pydantic schema same way the real tool would.
    try:
        validated = submit_tool.args_schema(**args).model_dump()
    except Exception as exc:  # noqa: BLE001
        log.warning("planner.force_tool_call.pydantic_invalid",
                    session_id=session_id, phase=phase, error=str(exc))
        await _broadcast(session_id, phase, "PM 工作流",
                         "warning",
                         f"tool_call args 不通过 Pydantic 校验: {str(exc)[:200]}",
                         error=str(exc)[:300])
        return False

    set_planner_output(session_id, phase, validated)
    log.info("planner.force_tool_call.captured",
             session_id=session_id, phase=phase,
             keys=list(validated.keys())[:8])
    return True


async def _force_tool_call_once(
    *,
    submit_tool: Any,
    system_msg: str,
    user_msg: str,
    provider: dict,
    model_name: str,
    temperature: float,
    max_tokens: int,
    log_label: str = "per_task",
) -> dict | None:
    """Single LiteLLM call that asks for one tool invocation. Returns
    the validated Pydantic dict on success, None on any failure.

    Compared to `_force_tool_call_fallback`, this does NOT touch the
    planner output store — the caller decides what to do with the dict.
    Used by `_run_phase_per_task` to fan out N independent calls whose
    results are aggregated in memory.

    2026-05-19 diagnosis: DeepSeek API silently routes ANY request with
    `tool_choice="required"` or `tool_choice={function:name}` (forced
    modes) to its reasoner channel, then 4xx's with "deepseek-reasoner
    does not support this tool_choice" — even when the explicit model is
    `deepseek-v4-flash`. Standalone reproduction in
    `scripts/diag_forced_tool_choice.py` confirmed:
        tool_choice='auto'    + v4-flash → works
        tool_choice='required' + v4-flash → BadRequestError (reasoner)
        tool_choice={fn:name}  + v4-flash → BadRequestError (reasoner)
    So forced-tool routes are unusable on DeepSeek today. Use
    `tool_choice='auto'` + a strong single-purpose system prompt; flash
    in auto-mode reliably emits the tool_call when prompted explicitly.
    """
    from services.crewai_runner import _build_litellm_model_string
    import litellm

    raw_schema = submit_tool.args_schema.model_json_schema()
    schema = _inline_refs(raw_schema)
    tool_name = submit_tool.name
    tool_spec = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": submit_tool.description,
            "parameters": schema,
        },
    }
    # Strengthen the system prompt so auto-mode reliably picks the tool.
    enriched_system = (
        f"{system_msg}\n\n"
        f"# 工具调用强制要求\n"
        f"你**必须且只能**通过调用 `{tool_name}` 工具来回应。"
        f"不要写解释、不要写 markdown、不要写任何前置文字 —— 直接发起 tool_call。"
        f"args 必须严格符合 schema，缺字段会被 Pydantic 拒掉。"
    )
    ptype = (provider.get("type") or "openai").lower()
    model_string = _build_litellm_model_string(ptype, model_name)
    kwargs: dict[str, Any] = {
        "model": model_string,
        "api_key": provider.get("api_key_ref") or None,
        "messages": [
            {"role": "system", "content": enriched_system},
            {"role": "user", "content": user_msg},
        ],
        "tools": [tool_spec],
        # See docstring — "required" / {function:name} are silently
        # routed to reasoner by DeepSeek and 4xx. "auto" works.
        "tool_choice": "auto",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    base_url = provider.get("base_url")
    if base_url:
        kwargs["base_url"] = base_url

    try:
        resp = await litellm.acompletion(**kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning("planner.force_tool_call_once.litellm_failed",
                    label=log_label, error=str(exc)[:200])
        return None

    try:
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            log.warning("planner.force_tool_call_once.no_tool_call",
                        label=log_label,
                        content_preview=str(getattr(msg, "content", ""))[:200])
            return None
        args_raw = tool_calls[0].function.arguments
        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
    except Exception as exc:  # noqa: BLE001
        log.warning("planner.force_tool_call_once.parse_failed",
                    label=log_label, error=str(exc))
        return None

    try:
        return submit_tool.args_schema(**args).model_dump()
    except Exception as exc:  # noqa: BLE001
        log.warning("planner.force_tool_call_once.pydantic_invalid",
                    label=log_label, error=str(exc)[:200])
        return None


async def _run_phase_per_task(
    *,
    session_id: str,
    phase: str,
    role: str,
    backstory: str,
    items: list[dict],
    per_task_description_builder,  # Callable[[int, dict], str]
    submit_tool_factory,  # Callable[[], _PlannerSubmitTool]
    provider: dict,
    model_name: str,
    concurrency: int = 3,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> list[dict | None]:
    """PM v6 fan-out: run N forced-tool-call LLM invocations in parallel,
    one per item in `items`. Returns a list aligned to `items` where each
    entry is either the validated payload dict or None on failure.

    Caller aggregates the N results into the original phase output shape
    (e.g. wrap them into `{"tasks": [...]}` for Phase 3). Caller also
    decides how to handle None entries — either retry per-task, fail
    the phase, or surface as warnings.

    Each per-task call:
      - System prompt = the phase's full backstory + a strict
        single-task directive
      - User prompt = `per_task_description_builder(i, item)` output
      - Forced tool_choice={function:name} on `submit_tool_factory()`
      - Uses `_force_tool_call_once` under the hood (inline refs,
        reasoner→flash swap, Pydantic validation).
    """
    if not items:
        return []

    sem = asyncio.Semaphore(max(1, concurrency))
    completed = 0
    failed = 0
    total = len(items)

    async def _broadcast_progress() -> None:
        try:
            from api.ws import manager
            await manager.broadcast("planner.per_task_progress", {
                "session_id": session_id,
                "phase": phase,
                "total": total,
                "completed": completed,
                "failed": failed,
                "running": max(0, total - completed - failed),
            })
        except Exception:
            pass

    base_system = (
        f"# 你的角色背景\n{backstory}\n\n"
        f"# 本次调用范围\n这一轮你**只**处理 1 个 task（不是全部）。"
        f"看完用户消息里那一个 task 的资料后，调一次 {submit_tool_factory().name} "
        f"工具一次性提交它的完整结构。不要写解释、markdown 或多余文字。"
    )

    async def _run_one(i: int, item: dict) -> dict | None:
        nonlocal completed, failed
        async with sem:
            user_msg = per_task_description_builder(i, item)
            tool = submit_tool_factory()
            result = await _force_tool_call_once(
                submit_tool=tool,
                system_msg=base_system,
                user_msg=user_msg,
                provider=provider,
                model_name=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                log_label=f"{phase}#item{i}",
            )
            if result is None:
                failed += 1
                log.warning("planner.per_task.item_failed",
                            session_id=session_id, phase=phase, item_index=i)
            else:
                completed += 1
            await _broadcast_progress()
            return result

    await _broadcast_progress()  # initial 0/total
    results = await asyncio.gather(
        *[_run_one(i, item) for i, item in enumerate(items)],
        return_exceptions=False,
    )
    log.info("planner.per_task.complete",
             session_id=session_id, phase=phase,
             total=total, completed=completed, failed=failed)
    return results


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
    max_iter: int = 8,
) -> dict:
    """Run one phase. Returns the captured payload dict on success.
    Raises on hard failure (after focused repair too).

    `max_iter`: per-attempt ReAct iteration cap. Default 8 — enough for
    DeepSeek-flash to draft a multi-task submit payload without burning
    iterations on rephrasing. Focused-repair uses `max(3, max_iter-2)`."""
    await _broadcast(session_id, phase, role, "started",
                     f"phase {phase} started")

    # Try 1: standard kickoff
    try:
        await run_crewai_agent(
            session_id=session_id,
            role=role, goal=goal, backstory=backstory,
            description=description, expected_output=expected_output,
            tools=tools, provider=provider, model_name=model_name,
            max_iter=max_iter, temperature=temperature, max_tokens=max_tokens,
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

    # Try 2: focused repair — same prompt + "上一次没调工具"提示
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
            max_iter=max(3, max_iter - 2),
            temperature=temperature, max_tokens=max_tokens,
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

    # Try 3: force tool_choice via direct LiteLLM (bypasses ReAct loop).
    # See _force_tool_call_fallback header for the 2026-05-19 root cause.
    await _broadcast(session_id, phase, role, "retry",
                     f"ReAct 两轮均未调到 {tools[0].name}，强制工具调用兜底中…")
    forced_ok = await _force_tool_call_fallback(
        session_id=session_id, phase=phase, submit_tool=tools[0],
        backstory=backstory, description=description,
        provider=provider, model_name=model_name,
        temperature=temperature, max_tokens=max_tokens,
    )
    if forced_ok:
        payload = pop_planner_output(session_id, phase)
        if payload is not None:
            await _broadcast(session_id, phase, role, "phase_completed",
                             f"phase {phase} completed (forced tool_choice)",
                             payload_preview=payload)
            return payload

    msg = (f"phase {phase}: agent 未能成功调用提交工具"
           f"（ReAct + 焦点修复 + 强制工具调用均失败）")
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
    max_iter: int = 8,
) -> dict:
    """Like _run_phase, but after a kickoff produces a captured payload
    we run a custom validator (e.g. coverage/conflict checks). On
    validation failure we *also* try a focused-repair kickoff that
    includes the validator errors in the prompt so the LLM can self-fix.

    This is what makes Plan A safe: Pydantic only verifies per-record
    structure; this layer enforces cross-record invariants (coverage,
    no duplicate indices, no path conflicts, prefix correctness).

    `max_iter` mirrors `_run_phase` (default 8)."""
    from src.tools.builtin.local._output_capture import pop_planner_output

    await _broadcast(session_id, phase, role, "started", f"phase {phase} started")

    tool_name = tools[0].name if tools else "submit_*"
    last_validator_errors: list[str] = []

    # Try 1: standard kickoff
    try:
        await run_crewai_agent(
            session_id=session_id, role=role, goal=goal, backstory=backstory,
            description=description, expected_output=expected_output,
            tools=tools, provider=provider, model_name=model_name,
            max_iter=max_iter, temperature=temperature, max_tokens=max_tokens,
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
        f"# 上次失败原因\n你上次的 {tool_name} 调用没通过校验：\n"
        f"  - {chr(10) + '  - '.join(last_validator_errors)}\n"
        f"请这次**严格按上面的错误说明**修正后再调一次。"
        if last_validator_errors
        else f"# 上次失败原因\n你没成功调用 {tool_name}。请这次"
             f"**务必调用** {tool_name} 工具一次性提交。"
    )
    repair_desc = f"{description}\n\n{error_hint}"
    try:
        await run_crewai_agent(
            session_id=session_id, role=role, goal=goal, backstory=backstory,
            description=repair_desc, expected_output=expected_output,
            tools=tools, provider=provider, model_name=model_name,
            max_iter=max(3, max_iter - 2),
            temperature=temperature, max_tokens=max_tokens,
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
        msg = (f"phase {phase} 焦点修复后仍未通过校验："
               + "; ".join(last_validator_errors[:5]))
        await _broadcast(session_id, phase, role, "phase_failed", msg, error=msg)
        raise RuntimeError(msg)

    # Try 3: forced tool_choice (only fires when ReAct produced no
    # payload at all — when it produced one but validation failed, that's
    # a content issue forced-call can't fix).
    await _broadcast(session_id, phase, role, "retry",
                     f"ReAct 两轮均未调到 {tool_name}，强制工具调用兜底中…")
    forced_ok = await _force_tool_call_fallback(
        session_id=session_id, phase=phase, submit_tool=tools[0],
        backstory=backstory, description=description,
        provider=provider, model_name=model_name,
        temperature=temperature, max_tokens=max_tokens,
    )
    if forced_ok:
        payload = pop_planner_output(session_id, phase)
        if payload is not None:
            last_validator_errors = validator(payload)
            if not last_validator_errors:
                await _broadcast(session_id, phase, role, "phase_completed",
                                 f"phase {phase} completed (forced tool_choice)",
                                 payload_preview=payload)
                return payload
            msg = (f"phase {phase} 强制工具调用后仍未通过校验："
                   + "; ".join(last_validator_errors[:5]))
            await _broadcast(session_id, phase, role, "phase_failed", msg, error=msg)
            raise RuntimeError(msg)

    msg = (f"phase {phase}: agent 未能成功调用提交工具"
           f"（ReAct + 焦点修复 + 强制工具调用均失败）")
    await _broadcast(session_id, phase, role, "phase_failed", msg, error=msg)
    raise RuntimeError(msg)


# ── Phase 4 cross-record validation + composition ───────────────────


def _dedup_path_specs(
    raw_specs: list[dict],
) -> tuple[list[dict], list[str]]:
    """PM v6 Phase 4 fan-out post-process: detect path collisions across
    independent per-task decisions and rename with `_2`/`_3` suffixes.

    Each task's LLM call doesn't see what other tasks picked, so two
    tasks may both claim e.g. `Assets/Scripts/Foo.cs`. Pure string
    operation, no LLM:
      - First occurrence wins
      - Subsequent collisions: insert `_2`, `_3`, ... before the
        extension (or at end if no extension)
    Returns (deduped_specs, rename_hints). Hint strings describe what
    was renamed so the PM log surfaces them to the user.
    """
    from pathlib import PurePosixPath
    used: set[str] = set()
    hints: list[str] = []
    out: list[dict] = []

    def _next_name(path: str) -> str:
        p = PurePosixPath(path)
        stem = p.stem
        suffix = p.suffix
        parent = str(p.parent)
        for n in range(2, 100):
            candidate_name = f"{stem}_{n}{suffix}" if suffix else f"{stem}_{n}"
            candidate = (
                f"{parent}/{candidate_name}" if parent and parent != "."
                else candidate_name
            )
            if candidate not in used:
                return candidate
        return f"{path}.collision_{len(used)}"

    for spec in raw_specs:
        new_paths: list[str] = []
        for p in spec.get("output_paths") or []:
            if not isinstance(p, str) or not p:
                continue
            if p in used:
                renamed = _next_name(p)
                hints.append(
                    f"path 冲突自动改名: '{p}' → '{renamed}' "
                    f"(task_index={spec.get('task_index')})"
                )
                new_paths.append(renamed)
                used.add(renamed)
            else:
                new_paths.append(p)
                used.add(p)
        out.append({**spec, "output_paths": new_paths})
    return out, hints


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


# Suffix groups that we treat as "same kind" — a task with ≥2 paths in
# any one group is flagged as bundled (likely a PM split miss).
# `.meta` is intentionally NOT in any group: Unity auto-generates one
# per asset, so 5 .cs naturally have 5 .meta — counting them would
# false-positive every code task.
_BUNDLING_GROUPS: dict[str, tuple[str, ...]] = {
    "C# 脚本": (".cs",),
    "Sprite/纹理": (".png", ".jpg", ".jpeg"),
    "音频": (".wav", ".mp3", ".ogg"),
    "Prefab": (".prefab",),
    "动画": (".anim", ".controller"),
    "3D 模型": (".fbx", ".blend", ".obj"),
}


def _classify_path_kind(path: str) -> str | None:
    """Return the artifact-kind group label for a path, or None if its
    suffix doesn't match any group (e.g. plain dirs, .meta, .md).
    """
    if not isinstance(path, str):
        return None
    p = path.lower()
    for label, suffixes in _BUNDLING_GROUPS.items():
        if any(p.endswith(s) for s in suffixes):
            return label
    return None


def _detect_same_kind_bundling(pathed_tasks: list[dict]) -> list[str]:
    """Flag tasks whose output_paths bundle artifacts the assigned Crew
    can't all produce. Two failure modes covered:

    1. **同质合并** (same-kind ≥2): one Crew Executor expected to write
       5 .cs files / 4 sprites in one shot — hits max_iter, leaves
       partial work + 文件不存在 errors.
    2. **异质混合** (mixed kinds): one task whose output_paths spans
       multiple artifact groups (e.g. AudioManager.cs + 4 .wav). Each
       Crew specialises in one kind, so the cross-kind item gets no
       producer. AudioManager.cs in 音频组 → 音频组 has no .cs writer
       → QA fails "文件不存在".

    Setup / final_qa skipped — they intentionally span everything.
    """
    warnings: list[str] = []
    for t in pathed_tasks:
        if t.get("kind") in ("setup", "final_qa"):
            continue
        paths = t.get("output_paths") or []
        if not isinstance(paths, list) or len(paths) < 1:
            continue
        title = t.get("title") or "<未命名 task>"

        # Pattern 1: ≥2 of the same kind.
        if len(paths) >= 2:
            for group_label, suffixes in _BUNDLING_GROUPS.items():
                matched = [
                    p for p in paths
                    if isinstance(p, str)
                    and any(p.lower().endswith(s) for s in suffixes)
                ]
                if len(matched) >= 2:
                    warnings.append(
                        f"task「{title}」打包了 {len(matched)} 个{group_label}产物 "
                        f"（{', '.join(matched[:3])}{'…' if len(matched) > 3 else ''}）—— "
                        f"建议拆成 {len(matched)} 个 task，每个产一个，"
                        f"以避免 Crew Executor 超 max_iter。"
                    )

        # Pattern 2: mixed kinds within one task.
        kinds_seen: dict[str, list[str]] = {}
        for p in paths:
            kind = _classify_path_kind(p)
            if kind:
                kinds_seen.setdefault(kind, []).append(p)
        if len(kinds_seen) > 1:
            summary = "; ".join(
                f"{label}({len(plist)})" for label, plist in kinds_seen.items()
            )
            warnings.append(
                f"task「{title}」混合了不同类型产物 [{summary}] —— "
                f"每个 Crew 只产一种 artifact，建议按 kind 拆成 "
                f"{len(kinds_seen)} 个独立 task（每个 kind 一个）；"
                f"特别是 .cs 必须独立成 task 送系统实现组。"
            )
    return warnings


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
                  "project_mgmt", "code_contract", "agent_assignment",
                  "art_style"]
    return all_phases.index(phase) >= all_phases.index(start_from)


_ART_OUTPUT_SUFFIXES = (".png", ".jpg", ".jpeg", ".tga", ".psd")


def _project_has_art_tasks(pathed_tasks: list[dict]) -> bool:
    """Phase 7 gating: only run StyleArchitect if at least one task in
    the project actually produces an image asset. Pure-code projects
    don't need an art_style.json — skip the LLM call entirely.
    """
    if not pathed_tasks:
        return False
    for t in pathed_tasks:
        paths = t.get("output_paths") or []
        if isinstance(paths, str):
            try:
                paths = json.loads(paths)
            except (json.JSONDecodeError, TypeError):
                continue
        if not isinstance(paths, list):
            continue
        for p in paths:
            if isinstance(p, str) and p.lower().endswith(_ART_OUTPUT_SUFFIXES):
                return True
    return False


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


def _longest_common_prefix(strings: list[str]) -> str:
    """Trivial LCP for clustering parent-task titles. Returns '' on empty."""
    if not strings:
        return ""
    head = strings[0]
    for s in strings[1:]:
        i = 0
        cap = min(len(head), len(s))
        while i < cap and head[i] == s[i]:
            i += 1
        head = head[:i]
        if not head:
            break
    return head


def _merge_into_crew_groups(
    pathed_tasks: list[dict],
    assignments: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Crew v5: cluster homogeneous Crew-assigned tasks under one parent.

    Cluster rule: two tasks merge iff (a) same performer_ref crew_id,
    (b) same set of upstream deps, (c) neither is kind='setup' / 'final_qa'.
    For each cluster of size >= 2:
      - Create a parent task (kind='crew', performer_kind='crew') at the
        end of the list. output_paths = union of children's; deps =
        cluster's shared upstream.
      - Each child gets `parent_task_id = <parent's array index>` and
        `deps = [parent_idx]` (scheduler skips children with non-NULL
        parent_task_id anyway, but keeping deps logically tight makes
        the DAG sane after the project_svc Pass 2 resolution).
      - Every other task's deps that referenced any cluster member are
        rewritten to reference the parent's index.

    Returns (new_pathed_tasks, new_assignments). If no cluster qualifies,
    returns the inputs unchanged (same identity).

    Index semantics: `parent_task_id` here is an INT (array index into
    the new list); project_svc.create_project_with_tasks must resolve
    it to a real task_id during its Pass-2 index→id translation, just
    like deps.
    """
    if not pathed_tasks:
        return pathed_tasks, assignments

    assignment_by_idx = {a["task_index"]: a for a in assignments}

    # Cluster by (crew_id, deps tuple)
    groups: dict[tuple, list[int]] = {}
    for i, t in enumerate(pathed_tasks):
        a = assignment_by_idx.get(i)
        ref = (a or {}).get("performer_ref") or {}
        if ref.get("kind") != "crew" or not ref.get("id"):
            continue
        if t.get("kind") in ("setup", "final_qa"):
            continue
        deps_key = tuple(sorted(t.get("deps") or []))
        groups.setdefault((ref["id"], deps_key), []).append(i)

    clusters = [(k, idxs) for k, idxs in groups.items() if len(idxs) >= 2]
    if not clusters:
        return pathed_tasks, assignments

    new_list: list[dict] = [dict(t) for t in pathed_tasks]
    new_assignments: list[dict] = [dict(a) for a in assignments]
    child_to_parent: dict[int, int] = {}

    for (crew_id, deps_key), member_indices in clusters:
        members = [pathed_tasks[i] for i in member_indices]
        union_paths: list[str] = []
        for m in members:
            for p in m.get("output_paths") or []:
                if p not in union_paths:
                    union_paths.append(p)
        titles = [m.get("title", "") for m in members]
        common = _longest_common_prefix(titles).rstrip(" ：—_-·、,，")
        if not common or len(common) < 2:
            common = f"批量{members[0].get('kind') or '产出'} × {len(members)}"
        else:
            common = f"{common} × {len(members)}"

        # Inline each child's title / detail / output_paths so the parent's
        # Head agent (e.g. Art Director) can see per-asset requirements
        # instead of just an empty "auto-merged" placeholder. Without this,
        # the Head sees N union'd paths but no per-path description and
        # the QA gate (PM contract check) reports "detail too vague".
        detail_lines: list[str] = [
            f"本任务为 Crew v5 fan-out 容器，包含 {len(members)} 个子产物，"
            f"请按下方清单逐个产出（每条对应一个 output_path）："
        ]
        for sub_no, m in enumerate(members, start=1):
            m_title = (m.get("title") or "").strip() or "(无标题)"
            m_detail = (m.get("detail") or "").strip() or "(无详细描述)"
            m_paths = m.get("output_paths") or []
            paths_line = ", ".join(m_paths) if m_paths else "(无)"
            detail_lines.append("")
            detail_lines.append(f"── 子产物 {sub_no}: {m_title}")
            detail_lines.append(f"   产出路径: {paths_line}")
            detail_lines.append(f"   要求: {m_detail}")

        parent_task = {
            "title": common,
            "detail": "\n".join(detail_lines),
            "deps": list(deps_key),
            "kind": "crew",
            "output_paths": union_paths,
            "output_schema": {},
            "performer_kind": "crew",
            "performer_id": crew_id,
            "agent_id": None,
        }
        parent_idx = len(new_list)
        new_list.append(parent_task)
        new_assignments.append({
            "task_index": parent_idx,
            "performer_ref": {"kind": "crew", "id": crew_id},
            "reason": f"v5 fan-out parent for {len(members)} children",
        })
        for child_idx in member_indices:
            child_to_parent[child_idx] = parent_idx
            new_list[child_idx]["parent_task_id"] = parent_idx
            new_list[child_idx]["deps"] = [parent_idx]

    # Rewrite every non-child task's deps that pointed at any cluster
    # member → parent's index (dedup'd, order preserved).
    for i, t in enumerate(new_list):
        if i in child_to_parent:
            continue
        old_deps = t.get("deps") or []
        new_deps: list = []
        seen: set = set()
        for d in old_deps:
            mapped = child_to_parent.get(d, d)
            if mapped not in seen:
                new_deps.append(mapped)
                seen.add(mapped)
        t["deps"] = new_deps

    return new_list, new_assignments


# ── Phase 6 deterministic assignment rules ─────────────────────────
#
# 2026-05-19: replaces the Phase 6 LLM (list_performers + submit_assignments).
# Routing by output_paths suffix is a pure rule-based decision — Crew
# scope is already well-defined per artifact kind, no reasoning needed.
# Saves ~30-90s per project (one LLM round-trip) + token cost + the
# DeepSeek tool_choice race conditions that ate Phase 5/6 repeatedly.
#
# Tier 1: unambiguous suffix → exactly one Crew.
# Tier 2: .prefab disambiguated by task.title/detail keywords (UI vs VFX vs Scene).
# Tier 3: tasks with no recognized suffix → 系统实现组 fallback (rare).


_SUFFIX_TO_CREW_NAME: dict[str, str] = {
    # Code
    ".cs": "系统实现组",
    # 2D images
    ".png": "2D 美术资产组",
    ".jpg": "2D 美术资产组",
    ".jpeg": "2D 美术资产组",
    # 3D models
    ".fbx": "3D 模型组",
    ".blend": "3D 模型组",
    ".obj": "3D 模型组",
    # Animation
    ".anim": "动画组",
    ".controller": "动画组",
    # Audio
    ".wav": "音频组",
    ".mp3": "音频组",
    ".ogg": "音频组",
    # Scene
    ".unity": "场景装配组",
    # ScriptableObject — code-adjacent data, treat like code
    ".asset": "系统实现组",
    # Material — usually applied alongside model/scene work
    ".mat": "场景装配组",
}

# .prefab disambiguation — checked against task.title + task.detail
_PREFAB_UI_KEYWORDS: tuple[str, ...] = (
    "canvas", "ui ", "ui-", "ui:", "ui面板", "ui层", "ui控件",
    "hud", "button", "image", "text", "menu", "面板", "按钮",
)
_PREFAB_VFX_KEYWORDS: tuple[str, ...] = (
    "particle", "particlesystem", "vfx", "粒子", "特效", "光效", "shader",
)


def _classify_prefab_owner(task: dict) -> str:
    """When a task's output_paths is dominated by .prefab, decide which
    Crew owns it by inspecting task title + detail. Defaults to
    场景装配组 (Scene Assembly) when neither UI nor VFX keywords match.
    """
    haystack = ((task.get("title") or "") + " " +
                (task.get("detail") or "")).lower()
    if any(k in haystack for k in _PREFAB_UI_KEYWORDS):
        return "UI 实现组"
    if any(k in haystack for k in _PREFAB_VFX_KEYWORDS):
        return "特效组"
    return "场景装配组"


def _pick_crew_for_task(task: dict) -> tuple[str, str]:
    """Return (crew_name, reason) for one task based on output_paths.

    Strategy: tally artifact kinds in output_paths. The majority kind
    wins; ties broken by a priority order (.cs > .unity > others) since
    .cs always deserves its own Crew (.cs mixed with anything else
    should have been caught + warned by _detect_same_kind_bundling).
    .prefab is special-cased via _classify_prefab_owner.
    """
    paths = [p for p in (task.get("output_paths") or []) if isinstance(p, str)]
    if not paths:
        return "系统实现组", "no output_paths — defaulting to 系统实现组"

    # Tally suffix → vote count
    tally: dict[str, int] = {}
    has_prefab = False
    for p in paths:
        lp = p.lower()
        if lp.endswith(".prefab"):
            has_prefab = True
            continue
        for suffix, crew in _SUFFIX_TO_CREW_NAME.items():
            if lp.endswith(suffix):
                tally[crew] = tally.get(crew, 0) + 1
                break

    # If any .cs is present, it dominates (per _detect_same_kind_bundling
    # warning, mixed-kind tasks should be split — but if we got here
    # with mixed, send to 系统实现组 so the .cs at least gets written).
    if tally.get("系统实现组") and not has_prefab:
        sample = next((p for p in paths if p.lower().endswith(".cs")), paths[0])
        return "系统实现组", f"output_paths 含 .cs ({sample}) → 系统实现组"

    if tally:
        crew = max(tally.items(), key=lambda kv: kv[1])[0]
        sample = paths[0]
        return crew, f"output_paths 主体后缀指向 {crew}（如 {sample}）"

    # Only .prefab — disambiguate
    if has_prefab:
        crew = _classify_prefab_owner(task)
        sample = next((p for p in paths if p.lower().endswith(".prefab")), "")
        return crew, f".prefab ({sample}) 按 title/detail keyword 路由到 {crew}"

    # Fallback
    return "系统实现组", f"无法识别后缀（{paths[0]}）— 默认 系统实现组"


async def _assign_performers_by_rule(pathed_tasks: list[dict]) -> list[dict]:
    """Deterministic Python-only replacement for Phase 6 LLM agent
    assignment. Returns assignments in the same shape the LLM tool
    submitted:
        [{task_index, performer_ref: {kind, id}, reason}, ...]

    Routing:
      - setup        → SKIP (Phase 4 pre-assigned the initializer agent)
      - final_qa     → QA Engineer agent (DB lookup by role)
      - regular      → Crew by `_pick_crew_for_task` suffix rule
    """
    # Build name → id map once. Only non-auto-generated crews qualify
    # (same filter list_performers uses).
    crew_rows = await crud.get_all("crews")
    crew_name_to_id: dict[str, str] = {}
    for r in crew_rows:
        if r.get("is_auto_generated"):
            continue
        if r.get("name") and r.get("id"):
            crew_name_to_id[r["name"]] = r["id"]

    qa_rows = await crud.get_all("agents", "role = ?", ("QA Engineer",))
    qa_agent_id = qa_rows[0]["id"] if qa_rows else None

    assignments: list[dict] = []
    for i, t in enumerate(pathed_tasks):
        kind = t.get("kind")
        if kind == "setup":
            continue
        if kind == "final_qa":
            if not qa_agent_id:
                log.error("planner.rule_assignment.no_qa_engineer")
                continue
            assignments.append({
                "task_index": i,
                "performer_ref": {"kind": "agent", "id": qa_agent_id},
                "reason": "final_qa 硬规则 → QA Engineer agent",
            })
            continue

        crew_name, reason = _pick_crew_for_task(t)
        crew_id = crew_name_to_id.get(crew_name)
        if not crew_id:
            log.error("planner.rule_assignment.crew_not_found",
                      task_index=i, crew_name=crew_name)
            continue
        assignments.append({
            "task_index": i,
            "performer_ref": {"kind": "crew", "id": crew_id},
            "reason": reason,
        })
    return assignments


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

    # Phase 7 (2026-05-20): if StyleArchitect ran, attach the project-
    # level art_style_spec so persist_svc → blueprint_writer can drop
    # it as `.mycrew_pending/art_style.json`. None for code-only
    # projects (Phase 7 skipped).
    art_style_spec = planner_cache_svc.get_phase_output(session_id, "art_style")

    out: dict = {
        "name": title or "未命名项目",
        "execution_kind": "crew",
        "architecture_overview": "\n".join(overview_parts) or "（无概念文档）",
        "tasks": final_tasks,
    }
    if isinstance(art_style_spec, dict) and art_style_spec:
        out["art_style_spec"] = art_style_spec
    return out


__all__ = ["run_crew"]
