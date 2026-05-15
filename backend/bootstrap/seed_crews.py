"""PM v4 — seed the eight predefined Crews + their member agents.

Phase 5 of the planner picks performers from a fixed menu (no `new_agent`
escape hatch); this module is what populates that menu. Each Crew is a
head → executor(s) → QA pipeline; the orchestrator walks the chain step
by step, injecting the previous step's structured payload into the next
step's prompt.

Seeding is idempotent: each agent + crew row is matched on role/name and
created only when absent. Re-running this never duplicates rows; safe to
call on every app start.

What lives where:
  - SEED_AGENTS: the 14 agents that participate in the Crews (head /
    executor / QA roles). Each gets a tool subset matched to its job.
  - SEED_CREWS: the 8 Crew definitions (Art / 3D Asset / Animation / VFX /
    System Impl / UI Impl / Audio / Scene Assembly) plus a list of
    "applicable_scenarios" Phase 5 reads to match a task to a Crew.

Step instructions are inlined here (not in a separate prompt file) so a
reviewer can scan the whole contract in one place and reasoners can grep
for the exact wording the LLM will see.
"""
from __future__ import annotations

import json

import structlog

from infra.repo import crud

log = structlog.get_logger()


# ── Common step-instruction prefix (PM v4 hard constraints) ────────

_STEP_PREAMBLE = """你接到的 task 已经经过 PM 4 个阶段完整规划。
`task.output_paths`（必产文件路径列表）+ `task.output_schema`（产物字段约束）+ `task.acceptance_notes`（验收标准）**全部已定**。
你**不允许**增删 task.output_paths、不允许修改 schema、不允许重新决定产物数量/位置。
你只在 PM 已给定的契约内做你这一步该做的事。

"""


# ── Helper: resolve tool names → ids, skipping unknowns silently ───

def _resolve_tools(tool_name_to_id: dict[str, str], names: list[str]) -> list[str]:
    return [tool_name_to_id[n] for n in names if n in tool_name_to_id]


# ── Agent definitions (14 total, all is_auto_generated=0) ─────────
#
# Notes on tool subsets:
#   - "Head" agents only emit a spec — they need write_file (to dump a
#     spec dict) + emit_output. No MCP needed.
#   - Executors carry domain tools (ComfyUI, Blender, Unity MCP, etc.)
#   - QA agents only read + emit_output verdict.

_UNIVERSAL = ["write_file", "read_file_local", "list_directory_local", "emit_output", "mkdir"]
_UNITY_FULL = [
    "manage_scene", "find_gameobjects", "manage_gameobject", "manage_components",
    "create_script", "script_apply_edits", "apply_text_edits", "validate_script",
    "get_sha", "delete_script", "manage_asset", "manage_prefabs",
    "manage_material", "manage_texture", "manage_ui", "manage_editor",
    "execute_menu_item", "read_console", "find_in_file", "execute_custom_tool",
    "manage_camera", "manage_graphics", "manage_packages", "manage_physics",
    "refresh_unity", "batch_execute",
]
_UNITY_ASSET_SUBSET = [
    "manage_asset", "manage_material", "manage_texture", "manage_graphics",
    "manage_packages", "manage_prefabs", "refresh_unity",
]
_COMFYUI = [
    "comfy_create_workflow_from_template", "comfy_validate_workflow",
    "comfy_enqueue_workflow", "comfy_get_job_status", "comfy_get_history",
    "comfy_list_local_models", "comfy_list_output_images", "comfy_upload_image",
]
_BLENDER = [
    "execute_blender_code", "get_scene_info", "get_object_info",
    "get_viewport_screenshot",
    "search_polyhaven_assets", "download_polyhaven_asset", "set_texture",
    "generate_hyper3d_model_via_text", "poll_rodin_job_status",
    "import_generated_asset",
]


SEED_AGENTS: list[dict] = [
    # ── Head / spec-emitters ───────────────────────────────────────
    {
        "role": "Art Director",
        "goal": "把任务的 output_paths 转化为可执行的美术规格（分辨率/风格/配色/命名），交给下游 Executor。",
        "backstory": "你是 MyCrew Art / 3D / Animation / VFX Crew 共享的 Head。只产规格，不直接动手做资产。",
        "tools": _UNIVERSAL,
    },
    {
        "role": "System Designer",
        "goal": "把任务的 output_paths（C# 脚本）转化为实现规格：类名/方法签名/状态机/算法步骤。",
        "backstory": "你是 System Impl Crew 的 Head。task.detail 给业务，你把它细化到方法级别。",
        "tools": _UNIVERSAL,
    },
    {
        "role": "UI/UX Designer",
        "goal": "把任务的 UI Prefab + 图片路径转化为 UI 规格：布局、图片清单、交互行为。",
        "backstory": "你是 UI Impl Crew 的 Head。产规格，不做实装。",
        "tools": _UNIVERSAL,
    },
    {
        "role": "Audio Designer",
        "goal": "把 task.output_paths（.wav）转化为音效规格：类型/时长/8-bit 关键词。",
        "backstory": "你是 Audio Crew 的 Head。产规格，不调合成器。",
        "tools": _UNIVERSAL,
    },
    {
        "role": "Level Designer",
        "goal": "扫描上游已完成 task 的产物，生成场景装配清单（prefab/位置/层级/脚本挂载/引用）。",
        "backstory": "你是 Scene Assembly Crew 的 Head；也可以作为单 agent 出关卡设计文档。",
        "tools": _UNIVERSAL + ["read_file_local", "list_directory_local"],
    },
    # ── Executors ─────────────────────────────────────────────────
    {
        "role": "Concept Artist",
        "goal": "按 Head spec 用 ComfyUI 出风格参考图作为下游视觉锚点。",
        "backstory": "Art Crew 第 1 个 Executor。只出 reference，不替代最终资产。",
        "tools": _UNIVERSAL + _COMFYUI,
    },
    {
        "role": "ComfyUI Image Generator",
        "goal": "对 task.output_paths 中每一个 PNG 路径，调 ComfyUI 真生图。严禁 write_file 写空 png 占位。",
        "backstory": "Art / UI Crew 的图像 Executor。一份 output_paths = 一份调用。",
        "tools": _UNIVERSAL + _COMFYUI,
    },
    {
        "role": "Technical Artist",
        "goal": "对每个生成资产用 Unity 资产工具（manage_asset/material/texture）配置导入设置；必要时切片 sprite sheet。",
        "backstory": "多 Crew 共用的 import / setup Executor。不创建新资产、不改路径。",
        "tools": _UNIVERSAL + _UNITY_ASSET_SUBSET + ["import_generated_asset"],
    },
    {
        "role": "3D Modeler",
        "goal": "按 Head spec 用 Blender MCP 建模，输出到 task.output_paths 中的 .fbx/.blend/.obj 路径。",
        "backstory": "3D Asset / Animation Crew 的建模 Executor。",
        "tools": _UNIVERSAL + _BLENDER,
    },
    {
        "role": "Animator",
        "goal": "按 Head spec 在 Blender 制作动画关键帧，导出 .anim 到 task.output_paths。",
        "backstory": "Animation Crew 的动画 Executor。",
        "tools": _UNIVERSAL + _BLENDER + ["import_generated_asset"],
    },
    {
        "role": "VFX Artist",
        "goal": "用 Blender / 内置工具创建粒子贴图/网格资源（_crew_cache），供下游 TA 在 Unity 装配 ParticleSystem。",
        "backstory": "VFX Crew 的 Executor。",
        "tools": _UNIVERSAL + _BLENDER,
    },
    {
        "role": "Unity Developer",
        "goal": "按 Head spec 用 Unity MCP 实装：写脚本 / 装配场景 / 配引用。task.output_paths 是必产清单。",
        "backstory": "System Impl / UI Impl / Audio / Scene Assembly Crew 共用的实装 Executor。",
        "tools": _UNIVERSAL + _UNITY_FULL,
    },
    {
        "role": "Audio Synthesizer",
        "goal": "对 task.output_paths 每个 .wav 调 synth_8bit_sfx 真合成。严禁 write_file 写空 wav 占位。",
        "backstory": "Audio Crew 的合成 Executor。8-bit 程序化合成，参数取自 Head spec。",
        "tools": _UNIVERSAL + ["synth_8bit_sfx"],
    },
    # ── QA ─────────────────────────────────────────────────────────
    {
        "role": "QA Engineer",
        "goal": "对照 PM 契约（task.output_paths / task.acceptance_notes）验收：文件存在 + 合法格式 + .meta 齐全。",
        "backstory": "所有 Crew 的最后一站。**不参考 Head spec 作为补充验收**；只看 PM 给的契约。",
        "tools": _UNIVERSAL + ["find_in_file", "read_console", "manage_editor"],
    },
    # ── Standalone single agents (not part of any Crew) ────────────
    # Phase 5 can pick these directly when a task is pure documentation
    # / narration — no need to spin up a full Crew for them.
    {
        "role": "Narrative Designer",
        "goal": "产出叙事 / 文案 / 剧情设计文档。",
        "backstory": "纯文档输出的单 agent。不实装、不画图。",
        "tools": _UNIVERSAL,
    },
]


# ── Crew definitions ──────────────────────────────────────────────
#
# step_instructions strings are written one-shot: each begins with
# _STEP_PREAMBLE (hard constraint) and then the step-specific body.

def _seq_step(role: str, instructions: str, *,
              step_role: str, progress_template: str = "") -> dict:
    return {
        "role": step_role,             # 'head' | 'executor' | 'qa'
        "agent_role": role,            # human-readable, resolved to agent_id at insert
        "step_instructions": _STEP_PREAMBLE + instructions,
        "progress_template": progress_template,
    }


SEED_CREWS: list[dict] = [
    # ── Art Crew (2D sprite / concept / UI image) ─────────────────
    {
        "name": "Art Crew",
        "applicable_scenarios": "2D sprite / 概念图 / UI 图 / 任何 PNG 图像资源（含 ComfyUI 真生图 + Unity 导入）",
        "sequence": [
            _seq_step(
                "Art Director",
                "把 task.output_paths 里的每一项转化为「产物执行规格」：分辨率（默认 64x64，按 task.detail 推断）、风格关键词 + 配色码、命名差异点。"
                "把 spec 写到一个 dict 里调 emit_output(payload=spec)，供下游使用。",
                step_role="head",
                progress_template="制定 {n} 项美术规格",
            ),
            _seq_step(
                "Concept Artist",
                "基于 Head 的 spec + task.output_paths 清单，用 ComfyUI 出「风格参考图」作为视觉锚点。"
                "参考图放 `<project>/output/_crew_cache/<task_id>/concept_*.png`（不入 task.output_paths）。"
                "不要直接生成最终资产。调 emit_output(payload={'reference_paths': [...]}) 报告。",
                step_role="executor",
                progress_template="出参考图 ({count}/{total})",
            ),
            _seq_step(
                "ComfyUI Image Generator",
                "对 task.output_paths 中**每一个**目标路径，调 comfy_create_workflow_from_template + comfy_enqueue_workflow 真生 PNG。"
                "参数取 Head spec、视觉参考取 Concept Artist 的 reference_paths。"
                "严禁用 write_file 写空 png 占位。"
                "调 emit_output(payload={'file_paths': [全部 task.output_paths]}) 报告。",
                step_role="executor",
                progress_template="生成 ({count}/{total}) PNG",
            ),
            _seq_step(
                "Technical Artist",
                "对每个生成的 PNG：用 manage_asset 设置 TextureType=Sprite + 配 pixel-per-unit；"
                "task.detail 暗示是 sprite sheet 时用 manage_texture 切片。"
                "不修改路径/文件名。调 emit_output(payload={'imported': [...]}) 报告导入 status。",
                step_role="executor",
                progress_template="导入 ({count}/{total}) sprite",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约验收：1) task.output_paths 每个文件存在且 size > 0；2) 是合法 PNG（首 8 字节 == \\x89PNG\\r\\n\\x1a\\n）；"
                "3) 同名 .meta 文件已生成。**不参考 Head spec 作为补充验收**。"
                "调 emit_output(payload={'verdict': 'pass'|'fail', 'file_paths': [...], 'issues': [...], 'summary': '...'})。",
                step_role="qa",
                progress_template="验收 {n} 个 PNG",
            ),
        ],
    },
    # ── 3D Asset Crew ─────────────────────────────────────────────
    {
        "name": "3D Asset Crew",
        "applicable_scenarios": "3D 模型（角色 / 道具 / 环境，输出 .fbx / .blend / .obj）",
        "sequence": [
            _seq_step(
                "Art Director",
                "把 task.output_paths（.fbx / .blend / .obj）转化为 3D 规格：多边形上限（pixel art → 低面；写实 → 高面）、UV / 材质要求 / LOD 级数、网格命名约定。"
                "调 emit_output(payload=spec) 提交。",
                step_role="head",
                progress_template="制定 3D 规格",
            ),
            _seq_step(
                "3D Modeler",
                "按 spec 用 Blender MCP 建模（execute_blender_code + polyhaven/rodin 辅助）。"
                "输出 .fbx 到 task.output_paths 中的对应路径。"
                "调 emit_output(payload={'file_paths': [...], 'poly_counts': {...}}) 报告。",
                step_role="executor",
                progress_template="建模 ({count}/{total})",
            ),
            _seq_step(
                "Technical Artist",
                "对每个 .fbx：用 manage_asset 配 Unity Model Importer（rig type / animation type / read-write enabled）。"
                "task.detail 提到 LOD → manage_asset 设置 LODGroup。"
                "调 emit_output(payload={'imported': [...]}) 报告。",
                step_role="executor",
                progress_template="导入 ({count}/{total}) 模型",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约验收：1) 每个 .fbx 文件存在 + 非空；2) FBX 文件首部 magic 合法（首字符 'K' 或 binary FBX 头）；3) 同名 .meta 已生成。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                progress_template="验收 {n} 个 .fbx",
            ),
        ],
    },
    # ── Animation Crew ────────────────────────────────────────────
    {
        "name": "Animation Crew",
        "applicable_scenarios": "角色 / 物体动画（输出 .anim / .controller）",
        "sequence": [
            _seq_step(
                "Art Director",
                "把 task.output_paths（.anim / .controller）转化为动画规格：帧率（30/60fps）、关键动作列表（idle/walk/jump/attack）、循环规则 + 过渡规则。"
                "调 emit_output(payload=spec) 提交。",
                step_role="head",
                progress_template="制定动画规格",
            ),
            _seq_step(
                "3D Modeler",
                "如 spec 需要骨骼绑定且上游模型无 rig：用 Blender MCP 给模型加 rig（armature + weight paint）。否则 emit_output(payload={'skipped': True, 'reason': '已有 rig'}) 跳过。",
                step_role="executor",
                progress_template="rig 准备",
            ),
            _seq_step(
                "Animator",
                "按 spec 在 Blender 制作动画关键帧，导出 .anim 或对应 Unity 格式到 task.output_paths。"
                "调 emit_output(payload={'file_paths': [...]}) 报告。",
                step_role="executor",
                progress_template="制作动画 ({count}/{total})",
            ),
            _seq_step(
                "Technical Artist",
                "对每个 .anim：用 manage_asset 配 AnimationClip import setting；必要时创建 AnimatorController 引用这些 clip。"
                "调 emit_output(payload={'imported': [...]}) 报告。",
                step_role="executor",
                progress_template="导入 ({count}/{total}) 动画",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约验收文件存在 + 非空 + .meta 齐全。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                progress_template="验收 {n} 个动画",
            ),
        ],
    },
    # ── VFX Crew ──────────────────────────────────────────────────
    {
        "name": "VFX Crew",
        "applicable_scenarios": "粒子特效 / 视觉效果（输出 VFX prefab 含 ParticleSystem）",
        "sequence": [
            _seq_step(
                "Art Director",
                "把 task.output_paths（VFX prefab / 粒子配置）转化为视觉规格：粒子数量上限（性能预算）、颜色 / 材质 / 持续时间 / 触发逻辑。"
                "调 emit_output(payload=spec) 提交。",
                step_role="head",
                progress_template="制定 VFX 规格",
            ),
            _seq_step(
                "VFX Artist",
                "用 Blender / 内置工具创建必要的贴图 / 网格 → 输出到 _crew_cache，调 emit_output(payload={'asset_paths': [...]}) 报告路径。",
                step_role="executor",
                progress_template="出 VFX 资产",
            ),
            _seq_step(
                "Technical Artist",
                "用 Unity MCP 在 task.output_paths 处创建 ParticleSystem prefab："
                "manage_prefabs.create 新建空 prefab → manage_components.add 添加 ParticleSystem → set_property 按 Head spec 配参数 → 关联 VFX Artist 的贴图。"
                "调 emit_output(payload={'file_paths': [prefab 路径...]}) 报告。",
                step_role="executor",
                progress_template="装配 ({count}/{total}) prefab",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约验收：prefab 文件存在 + 可加载（无 Missing reference）+ meta 齐全。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                progress_template="验收 VFX prefab",
            ),
        ],
    },
    # ── System Implementation Crew ────────────────────────────────
    {
        "name": "System Implementation Crew",
        "applicable_scenarios": "C# 玩法系统脚本（PlayerController / EnemyAI / 战斗 / 关卡生成等）",
        "sequence": [
            _seq_step(
                "System Designer",
                "把 task.output_paths（C# 脚本）转化为实现规格：类名 + namespace、public API 签名（方法 + 字段）、状态机 / 数据结构细节、关键算法步骤。"
                "task.detail 给业务语义；你把它细化到方法级别可执行。"
                "调 emit_output(payload=spec) 提交。",
                step_role="head",
                progress_template="制定实现规格",
            ),
            _seq_step(
                "Unity Developer",
                "按 spec 用 Unity MCP（create_script / script_apply_edits / apply_text_edits）创建 .cs 文件到 task.output_paths。"
                "代码要：(1) 含 spec 列的方法和签名 (2) 通过 validate_script 校验 (3) 在 Unity refresh 后无编译错误。"
                "调 emit_output(payload={'file_paths': [...]}) 报告。",
                step_role="executor",
                progress_template="写脚本 ({count}/{total})",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约：1) 每个 .cs 文件存在且包含 spec 要求的方法签名（find_in_file 或 read_file_local）；2) validate_script 通过；3) .meta 已生成。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                progress_template="验收 {n} 个 .cs",
            ),
        ],
    },
    # ── UI Implementation Crew ────────────────────────────────────
    {
        "name": "UI Implementation Crew",
        "applicable_scenarios": "UI 界面（Canvas + Image + Text + Button，含 UI 图片）",
        "sequence": [
            _seq_step(
                "UI/UX Designer",
                "把 task.output_paths（UI Prefab + UI 图片路径）转化为 UI 规格：布局（Canvas size / 锚点 / 层级）、图片资源清单（每元素一张图 + 分辨率）、交互行为。"
                "调 emit_output(payload=spec) 提交。",
                step_role="head",
                progress_template="制定 UI 规格",
            ),
            _seq_step(
                "ComfyUI Image Generator",
                "对 task.output_paths 中的 UI 图片路径，按 Head spec 真生 PNG。"
                "调 emit_output(payload={'file_paths': [...]}) 报告。",
                step_role="executor",
                progress_template="生成 ({count}/{total}) UI 图",
            ),
            _seq_step(
                "Unity Developer",
                "用 Unity MCP 创建 Canvas + UI 层级到 task.output_paths 中的 prefab 路径："
                "manage_gameobject create Canvas → manage_components add Image/Text/Button → set_property 引用上一步生成的 PNG。"
                "调 emit_output(payload={'file_paths': [prefab 路径...]}) 报告。",
                step_role="executor",
                progress_template="装配 ({count}/{total}) UI prefab",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约验收 UI prefab 完整性 + 图片 reference 解析 OK + .meta 齐全。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                progress_template="验收 UI prefab",
            ),
        ],
    },
    # ── Audio Crew ────────────────────────────────────────────────
    {
        "name": "Audio Crew",
        "applicable_scenarios": "音频（SFX / 简短 BGM 占位，8-bit 程序化合成，输出 .wav）",
        "sequence": [
            _seq_step(
                "Audio Designer",
                "把 task.output_paths（.wav）转化为音效规格：每个文件对应的音效类型（jump / hit / pickup / explosion / shoot / footstep / victory / death）、持续时间（毫秒）、8-bit 风格关键词。"
                "调 emit_output(payload=spec) 提交。",
                step_role="head",
                progress_template="制定音效规格",
            ),
            _seq_step(
                "Audio Synthesizer",
                "对 task.output_paths 每个 .wav：调 synth_8bit_sfx(name=<file stem>, sfx_type=<from spec>, duration_ms=<from spec>, out_dir=<file dir>) 真合成。"
                "严禁 write_file 写空 wav 占位。"
                "调 emit_output(payload={'file_paths': [...]}) 报告。",
                step_role="executor",
                progress_template="合成 ({count}/{total}) wav",
            ),
            _seq_step(
                "Unity Developer",
                "把每个 .wav 通过 manage_asset 配为 AudioClip（import setting：mono / load type / preload）。"
                "如 task.detail 要求，建一个 AudioManager.cs 关联这些 clip（可选）。"
                "调 emit_output(payload={'imported': [...]}) 报告。",
                step_role="executor",
                progress_template="导入 ({count}/{total}) AudioClip",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约：.wav 存在 + size > 44 字节（RIFF 头）+ RIFF/WAVE header 合法（首 4 字节 b'RIFF'、字节 8-12 b'WAVE'）+ .meta 齐全。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                progress_template="验收 {n} 个 wav",
            ),
        ],
    },
    # ── Scene Assembly Crew ───────────────────────────────────────
    {
        "name": "Scene Assembly Crew",
        "applicable_scenarios": "Unity 场景装配（实例化 prefab + 挂脚本 + 配引用，整合上游所有产物）",
        "sequence": [
            _seq_step(
                "Level Designer",
                "扫描上游所有已完成 task 的产物（read .mycrew/blueprint.json + list_directory_local Assets/），生成场景装配清单："
                "要实例化的 prefab 列表 + 在场景中的位置、GameObject 命名 + 父子关系、需要挂的脚本（哪个 GameObject 挂哪个上游 .cs）、关键引用设置。"
                "调 emit_output(payload=spec) 提交。",
                step_role="head",
                progress_template="制定装配清单",
            ),
            _seq_step(
                "Unity Developer",
                "按 spec 用 Unity MCP 装配场景："
                "manage_scene load → manage_gameobject create（带 prefab_path）→ manage_components add（挂脚本）→ set_property（配引用）→ manage_scene save。"
                "目标场景路径默认 Assets/Scenes/Main.unity（可在 task.output_paths 指定其他）。"
                "调 emit_output(payload={'file_paths': [场景路径...]}) 报告。",
                step_role="executor",
                progress_template="装配场景",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约验收：1) 场景文件存在；2) 用 manage_scene load 能成功加载（无 Missing reference 错误，看 read_console）；3) spec 中列的每个 GameObject 在场景里能 find_gameobjects 到。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                progress_template="验收场景",
            ),
        ],
    },
]


# ── Seeding entry ─────────────────────────────────────────────────

async def _ensure_agent(spec: dict, tool_name_to_id: dict[str, str],
                        llm_id_hint: str = "") -> str:
    """Insert one agent if absent (matched by role); return its id."""
    existing = await crud.get_all(
        "agents", "role = ? AND is_auto_generated = 0", (spec["role"],),
    )
    if existing:
        return existing[0]["id"]

    tool_ids = _resolve_tools(tool_name_to_id, spec["tools"])
    row = await crud.insert("agents", {
        "role": spec["role"],
        "goal": spec["goal"],
        "backstory": spec["backstory"],
        "reasoning": 0,
        "max_retry": 2,
        "memory_enabled": 0,
        "memory_path": None,
        "thinking_mode": 0,
        "tool_ids": json.dumps(tool_ids),
        "llm_id": llm_id_hint,
        "is_auto_generated": 0,
    }, id_prefix="agent_")
    log.info("seed.crew_agent_created", role=spec["role"], id=row["id"])
    return row["id"]


async def _ensure_crew(spec: dict, role_to_agent_id: dict[str, str]) -> str:
    """Insert one Crew if absent (matched by name); return its id."""
    existing = await crud.get_all("crews", "name = ?", (spec["name"],))
    if existing:
        return existing[0]["id"]

    sequence = []
    agent_ids: list[str] = []
    for step in spec["sequence"]:
        agent_role = step["agent_role"]
        agent_id = role_to_agent_id.get(agent_role)
        if not agent_id:
            log.warning("seed.crew_step_missing_agent",
                        crew=spec["name"], role=agent_role)
            continue
        sequence.append({
            "role": step["role"],
            "agent_id": agent_id,
            "step_instructions": step["step_instructions"],
            "progress_template": step["progress_template"],
        })
        agent_ids.append(agent_id)

    row = await crud.insert("crews", {
        "name": spec["name"],
        "process": "sequential",
        "agent_ids": json.dumps(agent_ids),
        "is_auto_generated": 0,
        "promoted_at": None,
        "applicable_scenarios": spec["applicable_scenarios"],
        "agent_sequence": json.dumps(sequence, ensure_ascii=False),
    }, id_prefix="crew_")
    log.info("seed.crew_created", name=spec["name"], id=row["id"], n_steps=len(sequence))
    return row["id"]


async def ensure_crew_pool(tool_name_to_id: dict[str, str]) -> dict[str, str]:
    """Seed the 14 agents + 8 Crews. Pick deepseek-flash as default LLM
    (head + QA use cheap tier; executors will be retunable later).

    Returns {crew_name: crew_id}.
    """
    # Default LLM (deepseek-flash) for all seed agents — Phase 5 / agent
    # editor can be retuned later. Matches the project initializer choice
    # and avoids the "first provider alphabetically" roulette.
    flash_models = await crud.get_all(
        "llm_models", "model_name LIKE ?", ("%deepseek%flash%",),
    )
    llm_id = ""
    if flash_models:
        m = flash_models[0]
        llm_id = f"{m['provider_id']}:{m['model_name']}"
    else:
        log.warning("seed.crew_pool.deepseek_flash_not_found")

    role_to_agent_id: dict[str, str] = {}
    for agent_spec in SEED_AGENTS:
        aid = await _ensure_agent(agent_spec, tool_name_to_id, llm_id)
        role_to_agent_id[agent_spec["role"]] = aid

    crew_name_to_id: dict[str, str] = {}
    for crew_spec in SEED_CREWS:
        cid = await _ensure_crew(crew_spec, role_to_agent_id)
        crew_name_to_id[crew_spec["name"]] = cid

    return crew_name_to_id
