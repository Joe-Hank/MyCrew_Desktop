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


class PerformerRef(BaseModel):
    """指向一个预设 performer（agent 或 Crew）。Phase 5 LLM 只能从
    `list_performers` 工具返回的池子里选，不允许新建。"""
    kind: Literal["agent", "crew"] = Field(
        ...,
        description="performer 种类。agent=单 agent 任务；crew=多步 Crew 任务（自带 QA）。",
    )
    id: str = Field(
        ...,
        description="agent_id 或 crew_id。**必须**是 list_performers 返回的某个 id；"
                    "禁止编造或返回 list_performers 未列出的 id。",
    )


class Assignment(BaseModel):
    """单个任务的 performer 匹配结果（v4：agent 或 crew 任选）。"""
    task_index: int = Field(..., description="0-based 任务索引")
    performer_ref: PerformerRef = Field(
        ...,
        description="选定的 performer 引用。从 list_performers 工具返回的池子里选。",
    )
    reason: str = Field(..., description="一句话解释为什么选这个 performer")


# ── Phase 5 (v5): 代码契约设计师 ──────────────────────────────────
# Inserted between project_mgmt (Phase 4) and agent_assignment (renumbered
# from Phase 5 to Phase 6 in human/log naming). The phase walks the
# pathed task list, finds every task that produces .cs files, and writes
# a per-task **named-symbol contract** the Crews must honour:
#
#   - Phase 5 LLM decides cross-task API names + signatures BEFORE
#     any Crew runs, so when Crew A writes PlayerController.cs and
#     Crew B writes EnemyAI.cs (which calls PlayerController.OnDeath),
#     both reference the same canonical name.
#   - Crew Head step CANNOT modify the contract (strict freeze, decision
#     Q5). Head only refines step_instructions within the contract.
#   - Crew QA step uses the contract to verify the generated .cs really
#     contains the listed public class / method / event / field
#     signatures (regex check + Unity console compile in v5 MVP).


class CodeContractExport(BaseModel):
    """One public symbol the task is contracted to produce."""
    kind: Literal["class", "interface", "struct", "enum",
                  "method", "field", "event", "property"] = Field(
        ...,
        description="符号种类。class/interface/struct/enum 是顶层声明；"
                    "method/field/event/property 是 class 成员。",
    )
    signature: str = Field(
        ...,
        description="完整 C# 签名行（单行，规范化空白）。例如："
                    "'public void Move(Vector2 direction)'、"
                    "'public class PlayerController : MonoBehaviour'、"
                    "'public event Action OnDeath'。"
                    "**禁止多行 / 嵌套泛型超过 2 层 / partial class** —— "
                    "v5 MVP regex 验证依赖单行规范格式。",
    )


class CodeContractFile(BaseModel):
    """All exports grouped by their target .cs file path. Multi-file
    tasks (e.g. "System Implementation Crew 产 Mineral.cs + MineralSpawner.cs")
    list each file separately so Crew QA can verify per-file."""
    path: str = Field(
        ...,
        description="相对路径，必须与该 task 的 output_paths 中的某条匹配。"
                    "例如 'Assets/Scripts/PlayerController.cs'",
    )
    exports: list[CodeContractExport] = Field(
        default_factory=list,
        min_length=1,
        description="该 .cs 文件必须包含的全部公共符号。Crew QA 验证时按"
                    "这个清单 regex 抽签名后比对；少一个则 task 校验失败。",
    )


class CodeContractImport(BaseModel):
    """A symbol this task depends on from another task's exports."""
    from_task_index: int = Field(
        ...,
        description="上游 task 的 0-based 索引（必须是当前 task 在依赖链中可见"
                    "的上游或同期 task，不允许向后引用）",
    )
    uses: list[str] = Field(
        ...,
        min_length=1,
        description="引用的符号短名（不带签名），例如 ['PlayerController.OnDeath', "
                    "'InventoryManager.AddItem']。验证时会与 from_task 的 "
                    "contract.files[*].exports 做交叉匹配，找不到 → 重跑 Phase。",
    )


class CodeContract(BaseModel):
    """The per-task code-level contract. Phase 5 emits one of these per
    task that produces .cs files; tasks that produce only non-code assets
    (sprites / wav / prefabs) get null (the field stays None).

    Decision Q1: per-task contract with internal file grouping. Decision
    Q5: strict freeze — Crew Head cannot mutate this; deviations cause
    Crew QA to fail the task, escalating to iterate flow."""
    namespace: str | None = Field(
        default=None,
        description="C# namespace 这些 export 都放在哪个 namespace 下。"
                    "可为空（用 global namespace）。",
    )
    files: list[CodeContractFile] = Field(
        ...,
        min_length=1,
        description="按目标 .cs 文件分组的 exports 清单",
    )
    imports: list[CodeContractImport] = Field(
        default_factory=list,
        description="依赖的上游 task 符号。可为空（task 不引用其他 task 的 API）。"
                    "每条 uses 都会被验证：必须在某个 from_task 的 exports 池里找到。",
    )


class TaskCodeContract(BaseModel):
    """Phase 5 输出的单条记录 — 把 contract 关联到一个 task_index。
    null contract 表示该 task 不产 .cs 文件，无契约。"""
    task_index: int = Field(..., description="0-based 任务索引")
    code_contract: CodeContract | None = Field(
        default=None,
        description="该任务的代码契约；null = 该任务不产 .cs 文件（如美术 / 音频 / "
                    "纯 prefab 任务），不需要约束符号。",
    )


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


class SubmitCodeContractsArgs(BaseModel):
    """Phase 5 (PM v5) 一次性提交全部 task 的 code_contract。
    覆盖率要求：list 长度 == 上游 task 数；每个 task_index 0..N-1 恰好
    出现一次（顺序不强求）。Pydantic 之后由 orchestrator 做交叉验证。"""
    contracts: list[TaskCodeContract] = Field(..., min_length=1)


# ── PM v6 (2026-05-19) per-task fan-out args schemas ────────────────
# Each one's parent multi-task args (above) requires a list; these
# single-task versions are dispatched once per task via
# `_run_phase_per_task` so each LLM call has a flat, narrow schema
# DeepSeek-flash + forced tool_choice can reliably emit.


class SubmitReviewedTaskSingleArgs(BaseModel):
    """One reviewed task — used by Phase 3 fan-out."""
    task: ReviewedTask = Field(
        ...,
        description="本次只为一个 task 补完 acceptance_notes / "
                    "input_sources / output_schema。完整 ReviewedTask 结构。",
    )


class SubmitPathSpecSingleArgs(BaseModel):
    """One path_spec — used by Phase 4 fan-out."""
    path_spec: PathSpec = Field(
        ...,
        description="本 task 的 output_paths 列表（一条 PathSpec）。",
    )


class SubmitCodeContractSingleArgs(BaseModel):
    """One TaskCodeContract — used by Phase 5 fan-out.
    `code_contract` may be None for non-code tasks (PNG / wav / prefab)."""
    record: TaskCodeContract = Field(
        ...,
        description="本 task 的 code_contract 决策（含 task_index 和 "
                    "code_contract dict 或 null）。",
    )


# ── Phase 7: 美术风格架构（StyleArchitect, 2026-05-20）─────────────
#
# 项目级一次性决策：在 PM Phase 1-6 之后追加，给定用户原始 prompt +
# Phase 1 ConceptDoc，输出全项目共享的「风格+模型+背景」三件套。
# 落盘到 `.mycrew_pending/art_style.json`，Crew 启动 art task 时由
# workflow_svc 读盘注入到第一个 fanout step 的 head_spec。
#
# 仅当项目含 .png/.jpg/.jpeg/.tga task 才触发（纯代码项目跳过）。


class ArtStyleSpec(BaseModel):
    """项目级美术风格规格——StyleArchitect 的唯一交付物。"""
    style_prompt: str = Field(
        ...,
        description="项目通用风格提示词字符串（中英混排可），含画风/笔触/"
                    "光照/调性关键词。会被拼到每张图最终 positive 的开头。"
                    "示例：'pixel art, 16-bit JRPG style, soft lighting, "
                    "warm palette, hand-drawn outline'",
    )
    fallback_style_prompt: str = Field(
        "pixel art, simple shapes, flat colors, 16-bit retro game asset",
        description="信息源不足时的兜底风格。**永远是像素风**——既保证"
                    "可玩可用，又跟手绘/写实不冲突。Crew 端如果 style_prompt "
                    "意外为空就用这个。",
    )
    checkpoint: str = Field(
        ...,
        description="推荐 ComfyUI checkpoint 文件名（含 .safetensors 后缀）。"
                    "应跟 style_prompt 匹配——比如 pixel 风用 sd 1.5 base，"
                    "写实用 majicmix，赛博朋克用 cyberpunk。若不确定填 "
                    "'cyberpunk.safetensors'（中性 fallback）",
    )
    background_mode: Literal["pixel_pil", "ai_node"] = Field(
        ...,
        description="透明背景策略。pixel_pil：脚本端 PIL 后处理（适合像素图/"
                    "纯色背景）。ai_node：ComfyUI 内置 RemoveBackground 节点"
                    "（适合写实/复杂背景）。**默认选 pixel_pil**——大多数"
                    "游戏素材是平面/像素，效果稳定且无 ML 黑盒边缘瑕疵。",
    )
    model_params: dict = Field(
        default_factory=lambda: {
            "steps": 20, "cfg": 6.5, "sampler": "euler", "scheduler": "normal",
        },
        description="ComfyUI KSampler 参数。Lightning 类 checkpoint 必须"
                    "把 steps 调到 4-8 + cfg 1.5-2.5。",
    )
    rationale: str = Field(
        ...,
        description="一段话解释为什么选这风格/模型/背景模式。用户阅读用。"
                    "10-50 字即可。",
    )


class SubmitArtStyleSpecArgs(BaseModel):
    """Phase 7 工具参数——提交项目级 ArtStyleSpec。"""
    spec: ArtStyleSpec = Field(..., description="完整 ArtStyleSpec 数据")


__all__ = [
    "CompletenessLabel",
    "ConceptDoc",
    "AtomicTask",
    "PathSpec",
    "SetupTaskSpec",
    "ReviewedTask",
    "PathedTask",
    "PerformerRef",
    "Assignment",
    "CodeContractExport",
    "CodeContractFile",
    "CodeContractImport",
    "CodeContract",
    "TaskCodeContract",
    "ArtStyleSpec",
    "SubmitConceptArgs",
    "SubmitAtomicTasksArgs",
    "SubmitReviewedTasksArgs",
    "SubmitPathedTasksArgs",
    "SubmitAssignmentsArgs",
    "SubmitCodeContractsArgs",
    "SubmitReviewedTaskSingleArgs",
    "SubmitPathSpecSingleArgs",
    "SubmitCodeContractSingleArgs",
    "SubmitArtStyleSpecArgs",
]
