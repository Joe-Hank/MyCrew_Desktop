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
    """项管阶段的产物。**不再由 LLM 直接 emit** — 由 orchestrator
    根据 LLM 提交的 PathSpec/SetupTaskSpec + 上游 ReviewedTask 组装。

    保留这个模型纯粹为了在 cache / persist_svc / blueprint_writer 那
    一路使用同一套类型；Phase 4 LLM 不再看到它的 schema（避免被复杂
    嵌套结构吓退）。
    """
    # 项管阶段允许引入第 3 种 kind = setup
    kind: Literal["regular", "final_qa", "setup"] = Field("regular")
    output_paths: list[str] = Field(
        ...,
        description="本任务产出的文件/目录的相对路径列表（项目根目录起算）",
    )
    # setup 任务在 phase 4 就 pre-assigned；其余 task 由 phase 5 填
    agent_id: str | None = Field(None)


# ── Phase 4 输入契约（LLM 实际看到的形态） ─────────────────────────


class PathSpec(BaseModel):
    """LLM 给一个上游审核任务推导出的输出路径。

    设计：LLM 一次只想一个 task 的事，不重复发上游字段；orchestrator
    在 Python 里把 PathSpec 跟 ReviewedTask merge 出最终 PathedTask。
    """
    task_index: int = Field(
        ...,
        ge=0,
        description="0-based 索引，指向上游 Phase 3 审核后的任务列表",
    )
    output_paths: list[str] = Field(
        ...,
        min_length=1,
        description="本任务产出的文件/目录的相对路径列表，必须以 Unity 模板"
                    "目录骨架里的某个目录为前缀（如 Assets/Scripts/...）",
    )


class SetupTaskSpec(BaseModel):
    """LLM 决定 setup 任务额外需要建的目录（除了所有 output_paths
    的父目录之外）。

    Orchestrator 会自动从所有 PathSpec.output_paths 推导出每个文件的
    父目录并去重，作为 setup 的基础目录列表；本字段供 LLM 补充那些
    "虽然没有任务直接产出，但属于项目骨架必须存在" 的目录（如
    Assets/Scenes/、Assets/Settings/ 等模板里有但本轮可能没人写的）。
    """
    extra_folders: list[str] = Field(
        default_factory=list,
        description="除了所有任务 output_paths 的父目录之外，还需要额外"
                    "创建的目录（如模板要求但本轮没任务用到的）",
    )


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
    """**重设计 v3.1**：LLM 只发它真正需要思考的两个东西 — 每个上游
    任务的路径列表 + setup 任务的额外目录。Orchestrator 用 Python
    代码做所有结构变换（插 setup 到 tasks[0]、给所有非 setup 任务的
    deps 加 0、合并 PathSpec 到 ReviewedTask 上）。

    这把 Phase 4 LLM 的输出体量从「8 个 task × 600 字 = 5KB」降到
    「8 行 task_index + paths = 1KB」，max_tokens 不再被打爆。"""
    path_specs: list[PathSpec] = Field(
        ...,
        min_length=1,
        description="每个上游审核任务对应一条 PathSpec；必须覆盖全部"
                    "上游任务（数量一致、索引齐全、不重复）",
    )
    setup: SetupTaskSpec = Field(
        ...,
        description="setup 任务的额外目录配置；常规情况下 extra_folders 可为空",
    )


class SubmitAssignmentsArgs(BaseModel):
    assignments: list[Assignment] = Field(..., min_length=1)


__all__ = [
    "CompletenessLabel",
    "ConceptDoc",
    "AtomicTask",
    "PathSpec",
    "SetupTaskSpec",
    "ReviewedTask",
    "PathedTask",
    "Assignment",
    "SubmitConceptArgs",
    "SubmitAtomicTasksArgs",
    "SubmitReviewedTasksArgs",
    "SubmitPathedTasksArgs",
    "SubmitAssignmentsArgs",
]
