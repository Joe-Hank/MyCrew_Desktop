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
    SubmitAssignmentsArgs,
    SubmitAtomicTasksArgs,
    SubmitConceptArgs,
    SubmitPathedTasksArgs,
    SubmitReviewedTasksArgs,
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
        "提交每个非 setup 任务的 agent 匹配结果。assignments 数组里每条 "
        "对应 task_index（0-based 指向上游任务列表），agent_id 必须是 "
        "现有 agents 列表里的真实 id，reason 一句话解释选择理由。"
        "kind=\"setup\" 的任务已经被项管 pre-assigned，本次提交跳过它。"
    )
    args_schema: type[BaseModel] = SubmitAssignmentsArgs
    _phase: ClassVar[str] = "agent_assignment"

    def _run(self, assignments: list[dict]) -> str:
        return self._capture({"assignments": assignments})


def make_submit_assignments_tool(session_id: str) -> SubmitAssignments:
    class _Bound(SubmitAssignments):
        _bound_session_id: ClassVar[str] = session_id
    return _Bound()


__all__ = [
    "make_submit_concept_tool",
    "make_submit_atomic_tasks_tool",
    "make_submit_reviewed_tasks_tool",
    "make_submit_pathed_tasks_tool",
    "make_submit_assignments_tool",
]
