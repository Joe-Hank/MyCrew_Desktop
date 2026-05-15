"""PM v3 — progressive-enrichment Pydantic models.

Each phase fills a strict subset of fields. Downstream phases inherit
the prior model so the contract grows but never breaks:

    ConceptDoc                              ← Phase 1 (主策划)
    AtomicTask                              ← Phase 2 (系统策划)
    ReviewedTask(AtomicTask)                ← Phase 3 (审核策划)
    PathedTask(ReviewedTask)                ← Phase 4 (项管)
    Assignment                              ← Phase 5 (指挥员)

The orchestrator never accepts a free-form dict between phases; each
submit_xxx tool validates against one of these models and rejects the
LLM with a structured error on mismatch. This is the single biggest
quality lever in the v3 rewrite — it replaces the "emit_output payload
is a dict, schema-described in prose" approach that failed on the
cyberpunk project (validation_failed across multiple tasks).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Phase 0: 完整度判定 ─────────────────────────────────────────────

CompletenessLabel = Literal["ONELINE", "PRD"]


# ── Phase 1: 游戏主策划 ─────────────────────────────────────────────


class ConceptDoc(BaseModel):
    """完整游戏概念草案。主策划的唯一交付物。"""
    title: str = Field(..., description="游戏标题，5-15 字")
    core_loop: str = Field(
        ...,
        description="一段话讲清楚核心循环（玩家做什么 → 得到什么反馈 → 下一步）",
    )
    systems: list[str] = Field(
        ...,
        description="系统名字列表，如 ['跳跃系统', '敌人 AI', '关卡进度']",
    )
    mechanics: list[str] = Field(
        ...,
        description="具体机制，如 ['双跳', '慢动作子弹时间', '连击 combo']",
    )
    art_style: str = Field(..., description="美术风格关键词，如 '低多边形 + 霓虹色'")
    target_player: str = Field(..., description="目标玩家描述")


# ── Phase 2: 系统策划 ──────────────────────────────────────────────


class AtomicTask(BaseModel):
    """原子级任务。系统策划拆出的初版任务节点。"""
    title: str = Field(..., description="任务名，简短")
    detail: str = Field(..., description="详细说明，至少 1 句话讲清楚做什么")
    deps: list[int] = Field(
        default_factory=list,
        description="0-based 索引，引用本任务列表里的前置任务",
    )
    kind: Literal["regular", "final_qa"] = Field("regular")
    est_complexity: Literal["small", "medium", "large"] = Field("medium")


# ── Phase 3: 审核策划 ──────────────────────────────────────────────


class ReviewedTask(AtomicTask):
    """审核策划补字段：验收标准 + 输入信息源 + 输出 schema。"""
    acceptance_notes: str = Field(
        ...,
        description="本任务的验收标准。QA agent 会读这个判断产出是否合格",
    )
    input_sources: list[str] = Field(
        default_factory=list,
        description="自然语言描述本任务依赖的信息源（如 '上游任务 #2 的输出', '设计文档 X 段落'）",
    )
    output_schema: dict = Field(
        ...,
        description="JSON Schema，必须含 file_path 字段（除非是 final_qa 类型）",
    )


# ── Phase 4: 项目管理 ──────────────────────────────────────────────


class PathedTask(ReviewedTask):
    """项管补字段：基于模板推导的输出路径。"""
    # 项管阶段允许引入第 3 种 kind = setup
    kind: Literal["regular", "final_qa", "setup"] = Field("regular")
    output_paths: list[str] = Field(
        ...,
        description="本任务产出的文件/目录的相对路径列表（项目根目录起算）",
    )
    # setup 任务在 phase 4 就 pre-assigned；其余 task 由 phase 5 填
    agent_id: str | None = Field(None)


# ── Phase 5: Agent 指挥员 ──────────────────────────────────────────


class Assignment(BaseModel):
    """单个任务的 agent 匹配结果。"""
    task_index: int = Field(..., description="0-based 任务索引")
    agent_id: str = Field(..., description="选定的现有 agent_id")
    reason: str = Field(..., description="一句话解释为什么选这个 agent")


# ── 工具 args schema ───────────────────────────────────────────────


class SubmitConceptArgs(BaseModel):
    concept: ConceptDoc


class SubmitAtomicTasksArgs(BaseModel):
    tasks: list[AtomicTask] = Field(..., min_length=1)


class SubmitReviewedTasksArgs(BaseModel):
    tasks: list[ReviewedTask] = Field(..., min_length=1)


class SubmitPathedTasksArgs(BaseModel):
    tasks: list[PathedTask] = Field(
        ...,
        min_length=2,
        description="第一项必须是 kind=setup 的初始化任务，其余依次跟上",
    )


class SubmitAssignmentsArgs(BaseModel):
    assignments: list[Assignment] = Field(..., min_length=1)


__all__ = [
    "CompletenessLabel",
    "ConceptDoc",
    "AtomicTask",
    "ReviewedTask",
    "PathedTask",
    "Assignment",
    "SubmitConceptArgs",
    "SubmitAtomicTasksArgs",
    "SubmitReviewedTasksArgs",
    "SubmitPathedTasksArgs",
    "SubmitAssignmentsArgs",
]
