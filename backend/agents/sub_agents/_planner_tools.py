"""PM v3 — 5 per-phase submit tools.

Each tool:
  - is bound to a (session_id, phase) via factory closure
  - declares a strict Pydantic args_schema (the LLM sees the exact field
    names + types in its function-calling schema)
  - on call: Pydantic validation already happened (CrewAI invokes _run
    with a validated dict); we only stash the payload via
    set_planner_output and return OK
  - on validation error: returned to the LLM via Pydantic's standard
    error message so it can self-correct within max_iter

This is the v3 quality lever — replacing the v2 emit_output style where
`payload: dict` was schema-described in prose. With these tools, LLMs
get the exact contract.
"""
from __future__ import annotations

from typing import ClassVar

import structlog
from pydantic import BaseModel

from src.tools.builtin._base import GuardedLocalTool
from src.tools.builtin.local._output_capture import set_planner_output

from agents.sub_agents._planner_models import (
    SubmitArtStyleSpecArgs,
    SubmitAssignmentsArgs,
    SubmitAtomicTasksArgs,
    SubmitCodeContractsArgs,
    SubmitCodeContractSingleArgs,
    SubmitConceptArgs,
    SubmitPathedTasksArgs,
    SubmitPathSpecSingleArgs,
    SubmitReviewedTasksArgs,
    SubmitReviewedTaskSingleArgs,
)

log = structlog.get_logger()


# ── Base class for all 5 ────────────────────────────────────────────


class _PlannerSubmitTool(GuardedLocalTool):
    """Common skeleton — subclasses set name / description / args_schema
    and override _phase. _run captures via the shared output channel."""

    _bound_session_id: ClassVar[str] = ""
    _phase: ClassVar[str] = ""
    # No permission_kind: pure data capture, no side effects.
    permission_kind: ClassVar[str | None] = None

    def _capture(self, payload: dict) -> str:
        sid = self._bound_session_id
        if not sid:
            return "[Error] Internal: planner submit tool not bound to a session."
        set_planner_output(sid, self._phase, payload)
        log.info("planner_submit.captured",
                 session_id=sid, phase=self._phase,
                 keys=list(payload.keys())[:8])
        return f"OK — phase '{self._phase}' output captured. End your turn with a one-line confirmation."


# ── Phase 1: 主策划 ────────────────────────────────────────────────


class SubmitConcept(_PlannerSubmitTool):
    name: str = "submit_concept"
    description: str = (
        "提交完整的游戏概念草案。系统策划阶段会基于这份草案拆任务。"
        "必须一次性提交完整的 ConceptDoc（含 title/core_loop/systems/"
        "mechanics/art_style/target_player 六字段）。"
    )
    args_schema: type[BaseModel] = SubmitConceptArgs
    _phase: ClassVar[str] = "concept"

    def _run(self, concept: dict) -> str:
        return self._capture({"concept": concept})


def make_submit_concept_tool(session_id: str) -> SubmitConcept:
    class _Bound(SubmitConcept):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


# ── Phase 2: 系统策划 ──────────────────────────────────────────────


class SubmitAtomicTasks(_PlannerSubmitTool):
    name: str = "submit_atomic_tasks"
    description: str = (
        "提交原子级任务列表。每个任务含 title/detail/deps/kind/"
        "est_complexity。deps 是 0-based 索引引用本列表里的前置任务。"
        "至少 1 个任务，末尾应有一个 kind=\"final_qa\" 的整体质检任务。"
    )
    args_schema: type[BaseModel] = SubmitAtomicTasksArgs
    _phase: ClassVar[str] = "system_design"

    def _run(self, tasks: list[dict]) -> str:
        return self._capture({"tasks": tasks})


def make_submit_atomic_tasks_tool(session_id: str) -> SubmitAtomicTasks:
    class _Bound(SubmitAtomicTasks):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


# ── Phase 3: 审核策划 ──────────────────────────────────────────────


class SubmitReviewedTasks(_PlannerSubmitTool):
    name: str = "submit_reviewed_tasks"
    description: str = (
        "提交审核后的任务链。每个任务在原子版基础上必须补 "
        "acceptance_notes（验收标准）、input_sources（信息源描述）、"
        "output_schema（含 file_path 字段的 JSON Schema）。"
        "如果发现原子版任务的依赖关系错误，直接在此次提交里修正。"
    )
    args_schema: type[BaseModel] = SubmitReviewedTasksArgs
    _phase: ClassVar[str] = "review"

    def _run(self, tasks: list[dict]) -> str:
        return self._capture({"tasks": tasks})


def make_submit_reviewed_tasks_tool(session_id: str) -> SubmitReviewedTasks:
    class _Bound(SubmitReviewedTasks):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


# ── Phase 4: 项目管理 ──────────────────────────────────────────────


class SubmitPathedTasks(_PlannerSubmitTool):
    name: str = "submit_pathed_tasks"
    description: str = (
        "为每个上游审核任务提交它的输出路径列表 + setup 任务的额外目录。"
        "**你不需要重发任务的标题/详情/schema/agent_id 等字段** — 它们"
        "会被代码自动从上游继承。你只发两块数据：\n"
        "  1. path_specs: 每条 {task_index, output_paths}，覆盖所有"
        "上游任务（数量一致、索引完整、不重复、路径不冲突）\n"
        "  2. setup: {extra_folders: [...]} — 模板里有但本轮没任务"
        "直接用的目录；常规情况留空数组即可\n"
        "setup 任务本身（mkdir 任务、agent 分配、deps 调整）由代码自动"
        "拼装，你不用管。"
    )
    args_schema: type[BaseModel] = SubmitPathedTasksArgs
    _phase: ClassVar[str] = "project_mgmt"

    def _run(self, path_specs: list[dict], setup: dict) -> str:
        return self._capture({"path_specs": path_specs, "setup": setup})


def make_submit_pathed_tasks_tool(session_id: str) -> SubmitPathedTasks:
    class _Bound(SubmitPathedTasks):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


# ── Phase 5: Agent 指挥员 ──────────────────────────────────────────


class SubmitAssignments(_PlannerSubmitTool):
    name: str = "submit_assignments"
    description: str = (
        "提交每个非 setup 任务的 performer 匹配结果（PM v4）。"
        "assignments 数组里每条对应 task_index（0-based 指向上游任务列表）："
        "performer_ref={kind, id}（kind 是 'agent' 或 'crew'，id **必须**"
        "是先前 list_performers 工具返回的池子里的某个真实 id），reason "
        "一句话解释选择理由。kind=\"setup\" 的任务已被项管 pre-assigned，"
        "本次提交跳过它。**严禁创建新 performer**：本工具没有 new_agent "
        "字段，编造或返回 list_performers 未列出的 id 会被 Pydantic 拒绝。"
    )
    args_schema: type[BaseModel] = SubmitAssignmentsArgs
    _phase: ClassVar[str] = "agent_assignment"

    def _run(self, assignments: list[dict]) -> str:
        return self._capture({"assignments": assignments})


def make_submit_assignments_tool(session_id: str) -> SubmitAssignments:
    class _Bound(SubmitAssignments):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


# ── Phase 5 (PM v5): 代码契约设计师 ────────────────────────────────


class SubmitCodeContracts(_PlannerSubmitTool):
    name: str = "submit_code_contracts"
    description: str = (
        "提交每个上游 task 的代码契约（PM v5）。contracts 数组每条含 "
        "task_index + code_contract（或 null）。"
        "**只给会产 .cs 文件的 task 写 contract**（看 task.output_paths 是否含 "
        ".cs 后缀）；产 PNG / wav / prefab / .unity 等非代码资产的 task，"
        "code_contract 必须填 null。"
        "contract.files[i].path 必须是该 task 的 output_paths 里某个 .cs 路径；"
        "exports[i].signature 必须是单行规范 C# 签名（不允许多行 / 注释 / 嵌套泛型 > 2 层）。"
        "imports[i].uses 引用的符号必须存在于 from_task_index 指向的 task 的 exports 池里 — "
        "Pydantic 通过后还会做交叉校验，找不到 → 拒绝 → 你被要求修正后重提。"
        "contracts 长度必须 == 上游 task 数；task_index 必须覆盖 0..N-1 不重不漏。"
    )
    args_schema: type[BaseModel] = SubmitCodeContractsArgs
    _phase: ClassVar[str] = "code_contract"

    def _run(self, contracts: list[dict]) -> str:
        return self._capture({"contracts": contracts})


def make_submit_code_contracts_tool(session_id: str) -> SubmitCodeContracts:
    class _Bound(SubmitCodeContracts):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


# ── PM v6 (2026-05-19) per-task fan-out submit tools ───────────────
#
# Each one carries a `_phase` value that maps to the same logical phase
# as its multi-task sibling — but per-task fan-out in
# `_run_phase_per_task` doesn't actually use `set_planner_output` (it
# returns the validated dict in-memory from `_force_tool_call_once`).
# The `_capture` `set_planner_output` write is therefore dead code in
# the fan-out path. We keep these tools subclass `_PlannerSubmitTool`
# anyway so the existing `make_*_tool` shape (factory binding session_id)
# is uniform across single + list variants.


class SubmitReviewedTaskSingle(_PlannerSubmitTool):
    name: str = "submit_reviewed_task_single"
    description: str = (
        "提交单个 task 的 ReviewedTask 数据。"
        "包含 acceptance_notes / input_sources / output_schema 三个补充字段。"
        "本次只处理 1 个 task（fan-out 模式），不要塞整张列表。"
    )
    args_schema: type[BaseModel] = SubmitReviewedTaskSingleArgs
    _phase: ClassVar[str] = "review"

    def _run(self, task: dict) -> str:
        return self._capture({"task": task})


def make_submit_reviewed_task_single_tool(session_id: str) -> SubmitReviewedTaskSingle:
    class _Bound(SubmitReviewedTaskSingle):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


class SubmitPathSpecSingle(_PlannerSubmitTool):
    name: str = "submit_path_spec_single"
    description: str = (
        "提交单个 task 的 PathSpec（task_index + output_paths）。"
        "本次只处理 1 个 task（fan-out 模式）。"
        "output_paths 必须使用模板允许的目录前缀。"
    )
    args_schema: type[BaseModel] = SubmitPathSpecSingleArgs
    _phase: ClassVar[str] = "project_mgmt"

    def _run(self, path_spec: dict) -> str:
        return self._capture({"path_spec": path_spec})


def make_submit_path_spec_single_tool(session_id: str) -> SubmitPathSpecSingle:
    class _Bound(SubmitPathSpecSingle):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


class SubmitCodeContractSingle(_PlannerSubmitTool):
    name: str = "submit_code_contract_single"
    description: str = (
        "提交单个 task 的 code_contract 决策（含 task_index + code_contract"
        " 或 null）。本次只处理 1 个 task（fan-out 模式）。"
        "output_paths 含 .cs → 写完整 contract；否则 code_contract 填 null。"
    )
    args_schema: type[BaseModel] = SubmitCodeContractSingleArgs
    _phase: ClassVar[str] = "code_contract"

    def _run(self, record: dict) -> str:
        return self._capture({"record": record})


def make_submit_code_contract_single_tool(session_id: str) -> SubmitCodeContractSingle:
    class _Bound(SubmitCodeContractSingle):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


# ── Phase 7: StyleArchitect (2026-05-20) ───────────────────────────


class SubmitArtStyleSpec(_PlannerSubmitTool):
    name: str = "submit_art_style_spec"
    description: str = (
        "提交项目级美术风格规格。**项目一次性**——所有 art Crew 会共享这份"
        "决策。包含 style_prompt / fallback_style_prompt / checkpoint / "
        "background_mode (pixel_pil 或 ai_node) / model_params / rationale "
        "六字段。整套规格落盘到 .mycrew_pending/art_style.json。"
    )
    args_schema: type[BaseModel] = SubmitArtStyleSpecArgs
    _phase: ClassVar[str] = "art_style"

    def _run(self, spec: dict) -> str:
        return self._capture({"spec": spec})


def make_submit_art_style_spec_tool(session_id: str) -> SubmitArtStyleSpec:
    class _Bound(SubmitArtStyleSpec):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


__all__ = [
    "make_submit_concept_tool",
    "make_submit_atomic_tasks_tool",
    "make_submit_reviewed_tasks_tool",
    "make_submit_pathed_tasks_tool",
    "make_submit_assignments_tool",
    "make_submit_code_contracts_tool",
    "make_submit_reviewed_task_single_tool",
    "make_submit_path_spec_single_tool",
    "make_submit_code_contract_single_tool",
    "make_submit_art_style_spec_tool",
]
