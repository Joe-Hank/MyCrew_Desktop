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
# Head agents are spec-emitters only — they read upstream, decide what
# the Executor will do, emit_output. Giving them `write_file` / `mkdir`
# tempts the LLM to skip emit_output and "just write the .cs/.png"
# itself (real production failure: 2026-05-20 System Designer dumped
# both MenuController + GameManager into one file via write_file
# instead of producing a spec). Strip the writers from Head's toolset
# so the only `Action` an LLM can pick is `emit_output`.
_HEAD_READONLY = ["read_file_local", "list_directory_local", "emit_output"]
# Git tools — Unity projects are git repos; the implementing developer
# needs status / log / diff to know what they changed and add/commit
# to checkpoint progress.
_GIT = [
    "git_status", "git_log", "git_diff_unstaged", "git_diff_staged",
    "git_add", "git_commit",
]
_UNITY_FULL = [
    "manage_scene", "find_gameobjects", "manage_gameobject", "manage_components",
    "create_script", "script_apply_edits", "apply_text_edits", "validate_script",
    "get_sha", "delete_script", "manage_asset", "manage_prefabs",
    "manage_material", "manage_texture", "manage_ui", "manage_editor",
    "execute_menu_item", "read_console", "find_in_file", "execute_custom_tool",
    "manage_camera", "manage_graphics", "manage_packages", "manage_physics",
    "refresh_unity", "batch_execute",
    # Added 2026-05-16 (P1 audit): Unity docs / reflection / test runner.
    # Doc lookup + reflection let the dev answer "how do I use this API"
    # without hallucinating; the test runner is how the Crew validates
    # a checkpoint or QA proves a Crew's work actually compiles+runs.
    "unity_docs", "unity_reflect", "run_tests", "get_test_job",
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
        "backstory": (
            "你是 MyCrew Art / 3D / Animation / VFX Crew 共享的 Head。"
            "**你不写文件、不动磁盘**——只产 spec 通过 emit_output 提交。"
            "工具栏里只有 read / list / emit_output，没有 write_file 是故意的。"
        ),
        "tools": _HEAD_READONLY,
    },
    {
        # 2026-05-20 image flow v2: PromptSmith 替代 Art Director 在
        # 2D 美术 / UI 实现 Crew 里的 Head 位置。它**只为单张图写
        # 主体提示词**——风格已由 PM Phase 7 StyleArchitect 项目级
        # 决定，PromptSmith 在 prev_payload.art_style_spec 里能看到。
        "role": "PromptSmith",
        "goal": (
            "为每张待生成的图写出**单一主体**的 subject_prompt（不含风格、"
            "不含负面、不含项目级关键词）。风格已经在项目 art_style_spec 里"
            "定好——你只补主体、动作、构图角度。"
        ),
        "backstory": (
            "你是 ComfyUI 图流的提示词工程师。\n\n"
            "# 输入信号（按重要性）\n"
            "- task.detail：单张图的具体描述\n"
            "- task.output_paths：决定文件名（暗示主体）\n"
            "- task.output_schema：决定尺寸\n"
            "- prev_payload.art_style_spec：**项目级**风格 + checkpoint + "
            "  background_mode。你不该重复 style_prompt 的内容——它会被"
            "  自动拼到你输出的前面。\n\n"
            "# 你必须输出（emit_output payload）\n"
            "```\n"
            "{\n"
            "  'prompts': {\n"
            "    '<output_path>': {\n"
            "      'subject_prompt': '单一主体描述',\n"
            "      'seed': <int>\n"
            "    }, ...\n"
            "  }\n"
            "}\n"
            "```\n\n"
            "# 单图单主体铁律\n"
            "- ✅ 'Billy Butcher, frontal portrait shot, leather coat, "
            "stern expression, shoulders up'\n"
            "- ❌ 'Billy Butcher and Homelander side-by-side'（多主体）\n"
            "- ❌ 'character turnaround, front side back views'（三视图）\n"
            "- ❌ 'character in multiple poses'（多姿势）\n"
            "- ❌ 'three different angles'（多角度）\n"
            "**禁止任何让 ComfyUI 在一张图里画多个主体/多个视角/多个姿势"
            "的描述**。需要 N 张不同视角 → PM 应该拆 N 个 task，每个 "
            "task 一张图。\n\n"
            "# 严禁\n"
            "- 在 subject_prompt 里加风格关键词（如 'pixel art / "
            "  photorealistic'）——会跟项目级 style_prompt 冲突\n"
            "- 在 subject_prompt 里加质量词（'high quality / masterpiece / "
            "  detailed'）——SD 自己会处理\n"
            "- 写 negative_prompt（FLUX 不支持，未来扩展再说）\n"
            "- 直接生图（你只出 prompt，下游 Generator 是脚本）\n"
            "- 多主体 / 多视角 / 多姿势 / spritesheet / atlas 类描述\n\n"
            "# 风格\n"
            "用 emit_output **工具**调用提交。完事用一句中文确认。"
        ),
        "tools": _HEAD_READONLY,
    },
    {
        "role": "StyleArchitect",
        "goal": "项目级美术风格决策——一次性敲定风格关键词 + checkpoint + 透明背景模式。",
        "backstory": (
            "PM Phase 7 的 head agent。**项目一次性**——所有 art Crew 共享。"
            "看用户原始 prompt + ConceptDoc，产 ArtStyleSpec。详细规则见 "
            "_planner_prompts.PHASE7_BACKSTORY。"
        ),
        "tools": _HEAD_READONLY,
    },
    {
        "role": "System Designer",
        "goal": "把任务的 output_paths（C# 脚本）转化为实现规格：类名/方法签名/状态机/算法步骤。",
        "backstory": (
            "你是 System Impl Crew 的 Head。task.detail 给业务，你把它细化到方法级别。"
            "**你不写 .cs 文件**——那是下游 Unity Developer 的活。"
            "你只通过 emit_output 提交 spec dict。"
        ),
        "tools": _HEAD_READONLY,
    },
    {
        "role": "UI/UX Designer",
        "goal": "把任务的 UI Prefab + 图片路径转化为 UI 规格：布局、图片清单、交互行为。",
        "backstory": (
            "你是 UI Impl Crew 的 Head。**产规格不写文件**——emit_output 提交。"
        ),
        "tools": _HEAD_READONLY,
    },
    {
        "role": "Audio Designer",
        "goal": "把 task.output_paths（.wav）转化为音效规格：类型/时长/8-bit 关键词。",
        "backstory": (
            "你是 Audio Crew 的 Head。**产规格不调合成器**——emit_output 提交。"
        ),
        "tools": _HEAD_READONLY,
    },
    {
        "role": "Level Designer",
        "goal": "扫描上游已完成 task 的产物，生成场景装配清单（prefab/位置/层级/脚本挂载/引用）。",
        "backstory": (
            "你是 Scene Assembly Crew 的 Head；也可以作为单 agent 出关卡设计文档。"
            "**只读 + emit_output，不写 .unity 文件**。"
        ),
        "tools": _HEAD_READONLY,
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
        "goal": "对 task.output_paths 中每一个 PNG 路径，按 task.output_schema 的 width/height 调 ComfyUI 真生图。严禁 write_file 写空 png 占位。",
        "backstory": "Art / UI Crew 的图像 Executor。一份 output_paths = 一份调用。尺寸来自 PM 契约（task.output_schema.width/height），不是 Head spec。",
        "tools": _UNIVERSAL + _COMFYUI + ["verify_image_dimensions"],
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
        # _BLENDER already includes import_generated_asset.
        "tools": _UNIVERSAL + _BLENDER,
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
        # +_GIT (2026-05-16 P1): checkpoint progress + diff own changes.
        "tools": _UNIVERSAL + _UNITY_FULL + _GIT,
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
        "goal": (
            "对照 PM 契约 + 上游 verdict + task.detail 综合验收。任一上游"
            "Executor 报 fail 必须 propagate；PM output_paths 为空但 "
            "task.detail 列了具体产物时，自己从 detail 推导清单后校验。"
        ),
        "backstory": (
            "你是 Crew 的最后一站。**职责是综合判定，不是只看一个契约就盖章。**\n\n"
            "# 强制规则（顺序判定，遇 fail 立刻 emit_output 不继续往下查）\n\n"
            "**规则 1：propagate 上游 verdict**\n"
            "读 prev_step_payload（上一步 Executor 的输出）。若其 verdict 不在 "
            "{pass, passed, success, ok} 中，**必须** emit_output("
            "verdict='fail', issues=[...原样带上 Executor 的 issues + 一条"
            "「上游 Executor verdict=X，无法独立验收通过」])。**不允许**因为"
            "「文件凑巧存在」就帮 Executor 翻案。\n\n"
            "**规则 2：契约空但 detail 有要求**\n"
            "若 task.output_paths 为空数组：扫 task.detail 文本，若发现具体"
            "扩展名（.cs / .png / .prefab / .unity / .wav / .asset / .meta）"
            "或具体路径模式（Assets/... / scripts/...），说明 PM 契约本身有"
            "漏。此时**自己从 detail 推导期望文件清单**做实际检查；任一推导"
            "项缺失就 verdict='fail'，issues 中说明「PM output_paths 为空但 "
            "task.detail 要求 X」。**不允许**因「契约 0 项」就直接 pass。\n\n"
            "**规则 3：契约有 output_paths**\n"
            "对契约里的每一项用 read_file_local / list_directory_local / "
            "find_in_file 实际验证：文件存在 + size > 0 + 合法格式 + .meta "
            "齐全（.cs/.png/.prefab/.unity 都需 .meta）。任一失败 verdict='fail'。\n\n"
            "**规则 4：纯文档/查询任务**\n"
            "若 task.output_paths 为空 且 task.detail 也不含任何文件扩展名/"
            "路径提示（纯需求澄清、纯参数表）：才可以 verdict='pass'。\n\n"
            "# emit_output 强制字段\n"
            "必带：\n"
            "- `verdict`：固定取值 'pass' / 'fail' / 'partial_pass'\n"
            "- `file_paths`：实际看到的文件列表（pass 时为契约/推导清单全集，"
            "fail 时填实际存在的子集）\n"
            "- `issues`：fail/partial_pass 时必填，pass 时为 []\n"
            "- `summary`：一句话总结判定依据\n\n"
            "# 严禁\n"
            "- 不写文件、不 mkdir、不 git。你只判定，不修复。\n"
            "- 不允许 verdict 字段缺省（缺省 = 0 信号 = 默认失败）。\n"
            "- 不允许照搬「契约空 → 0 项检查 → pass」的死板逻辑——这是上一版"
            "QA Engineer 出过事的姿势。"
        ),
        # +run_tests/get_test_job (P1): when a Crew claims it produced
        # a runnable artifact (script / scene), QA can fire Unity's
        # test runner to confirm — much stronger signal than "file
        # exists + size > 0".
        # +verify_image_dimensions: Art/UI Crew QA reads PNG IHDR and
        # compares to task.output_schema.width/height (PM contract).
        "tools": (
            _UNIVERSAL
            + ["find_in_file", "read_console", "manage_editor"]
            + ["run_tests", "get_test_job"]
            + ["verify_image_dimensions"]
        ),
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
    # Debugger — runs after final_qa when verdict != pass, attempts
    # *bounded* automated repair. See create_workflow._normalize_tasks
    # for the canonical task detail + scope guard. Tool set mirrors
    # Unity Developer + git so it can: read console errors, inspect
    # missing references, edit C# scripts, re-import assets, and diff
    # its own work before / after. NO Blender, NO ComfyUI — Debugger
    # is not allowed to regenerate missing assets (that's a Crew job).
    {
        "role": "Debugger",
        "goal": (
            "读 final_qa 的 issue 列表，在白名单作用域内（编译错 / "
            "Missing Reference / 资产导入设置 / 路径大小写 / "
            "emit_output payload 格式）逐条尝试修复；超出作用域的升级到 "
            "issues_escalated，由用户人工处理。"
        ),
        "backstory": (
            "你是项目尾的受限修复 agent。**严禁**：①生成新文件来填补缺失产出（让原 "
            "Crew 重跑去）；②动业务逻辑（'为什么吃豆人不吃豆子'是设计问题，不是 bug）；"
            "③跨 task 改设计。**只做明显的低风险修复**。每个修复完成调 emit_output "
            "报告改了什么文件、为什么。"
        ),
        "tools": (
            _UNIVERSAL
            + _UNITY_FULL
            + _GIT
        ),
    },
]


# ── Crew definitions ──────────────────────────────────────────────
#
# step_instructions strings are written one-shot: each begins with
# _STEP_PREAMBLE (hard constraint) and then the step-specific body.

def _seq_step(role: str, instructions: str, *,
              step_role: str, progress_template: str = "",
              fanout: dict | None = None,
              kind: str | None = None) -> dict:
    """Build one step dict for a Crew's agent_sequence.

    `fanout`: when non-None, marks this step as a parallel fan-out point.
    The runner (workflow_svc._run_crew) will look up every task row whose
    `parent_task_id == <this Crew task>.id` and dispatch them concurrently
    (asyncio.gather + asyncio.Semaphore(fanout["concurrency_cap"]))
    rather than running the step once on the parent. Crew v5 (2026-05-19):
    homogeneous sub-tasks (5 AI scripts / 4 sprites / 6 SFX) get one
    parent crew_group + N children; only the Executor step inside the
    Crew fans out, while Head/QA stay sequential and see unified spec/
    aggregated results.

    Shape: `{"concurrency_cap": int}` — extensible to future fields like
    `mode`, `batch_size`, etc.

    `kind`: optional dispatch override. Currently only one value used:
    `"script_qa"` swaps the LLM QA step for `services.qa_script.
    verify_task_qa` — deterministic Python checks (file/dim/magic/
    contract) rather than a CrewAI agent. The `agent_role` is kept for
    UI continuity (QA Engineer card stays in the team page) but the
    agent record isn't dispatched.
    """
    step: dict = {
        "role": step_role,             # 'head' | 'executor' | 'qa'
        "agent_role": role,            # human-readable, resolved to agent_id at insert
        "step_instructions": _STEP_PREAMBLE + instructions,
        "progress_template": progress_template,
    }
    if fanout is not None:
        step["fanout"] = fanout
    if kind is not None:
        step["kind"] = kind
    return step


SEED_CREWS: list[dict] = [
    # ── Art Crew (2D sprite / concept / UI image) ─────────────────
    {
        "name": "2D 美术资产组",
        "applicable_scenarios": "**.png / .jpg / .jpeg 二维图像专属**（2D sprite / 概念图 / UI 图标 / 角色立绘 / 物品图）。ComfyUI 真生图 + Unity sprite 导入。**禁止用于 .fbx / .blend / .obj —— 那是 3D 模型组**。",
        "sequence": [
            _seq_step(
                # 2026-05-20 image flow v2: 替换 Art Director 为
                # PromptSmith。风格已由 PM Phase 7 定到项目级；这一
                # 步只针对每张图写「单一主体」的 subject_prompt。
                "PromptSmith",
                "为 task.output_paths 里**每一张**待生成的图写主体 prompt。\n\n"
                "## 你看到什么\n"
                "- task.detail：本任务每张图的具体描述\n"
                "- task.output_paths：决定文件名（暗示主体）\n"
                "- prev_payload.art_style_spec：**项目级风格**——你 **不要**"
                "  在 subject_prompt 里重复任何风格/调性/媒介关键词，那是"
                "  下游 Generator 自动拼到前面的事\n\n"
                "## 你必须输出（emit_output payload）\n"
                "```\n"
                "{\n"
                "  'prompts': {\n"
                "    '<output_path_1>': {\n"
                "      'subject_prompt': '单一主体的描述',\n"
                "      'seed': <int>\n"
                "    },\n"
                "    '<output_path_2>': { ... }\n"
                "  }\n"
                "}\n"
                "```\n\n"
                "## 单图单主体铁律（违反就重做）\n"
                "- ✅ 'Billy Butcher, frontal head-and-shoulders portrait, "
                "leather coat, stern expression'\n"
                "- ❌ 'Billy Butcher, Homelander, Train, side by side'（多主体）\n"
                "- ❌ 'character turnaround front side back'（三视图）\n"
                "- ❌ 'spritesheet of 4 walking frames'（多帧）\n"
                "- ❌ 'in different poses'（多姿势）\n"
                "**如果 task 要求多张图，每张图各写一个 subject_prompt，"
                "不要把多个主体塞进同一张图。**\n\n"
                "## 严禁\n"
                "- 在 subject_prompt 里写 'pixel art / photorealistic / "
                "masterpiece / high quality'——风格和质量词由 Generator 拼\n"
                "- 写 negative_prompt（当前不支持）\n"
                "- 多主体 / 多视角 / spritesheet 类描述\n"
                "- 在 Thought 里写 'Action: emit_output' 当成调用（必须真用工具）\n",
                step_role="head",
                progress_template="为 {n} 张图写单图主体 prompt",
            ),
            # 2026-05-19: 删掉 Concept Artist 步骤。原设计是"出参考图作为
            # 视觉锚点"，但 ComfyUI `comfy_create_workflow_from_template`
            # 接收的 params 是 width/height/positive_prompt/negative_prompt
            # 字符串，没有 reference image 输入字段（除非模板用
            # IP-Adapter/ControlNet，目前没用）。Concept Artist 出的 PNG
            # 下游完全消费不了 → 浪费一次 ComfyUI 调用 + 中间步骤失败时
            # halt rule 把整个 Crew 拖死。Head 直接产 prompt 给 Generator。
            _seq_step(
                "ComfyUI Image Generator",
                # Stage 3 (2026-05-20): the executor step is now executed
                # by `services.image_gen_script.generate_image_for_child`
                # — a deterministic Python ComfyUI HTTP client. No LLM
                # involved. Step instructions retained as documentation
                # of what the script does, but workflow_svc dispatches
                # by `kind="script_comfy_generate"` and never reads the
                # text below.
                "[脚本执行，不调 LLM] 取 Head emit_output 的 prompts 映射，"
                "对每个 output_path 调 ComfyUI HTTP API 真生图：build txt2img "
                "workflow JSON → POST /prompt → poll /history → fetch PNG → "
                "PIL 缩放到契约尺寸 → 落盘到 root_path/output_path。",
                step_role="executor",
                progress_template="生成 ({count}/{total}) PNG",
                # ComfyUI is local + GPU-bound — 1 generation at a time.
                fanout={"concurrency_cap": 1},
                kind="script_comfy_generate",
            ),
            _seq_step(
                "Technical Artist",
                "[脚本执行，不调 LLM] 按 suffix 规则映射 Unity TextureImporter 字段："
                "textureType (Sprite/Default/NormalMap) / filterMode (Point/Bilinear) / "
                "wrapMode / mipmapEnabled / spriteMode / alphaIsTransparency / maxTextureSize。"
                "对每个产出文件调 Unity MCP `manage_asset action=modify`，最后 refresh_unity。",
                step_role="executor",
                progress_template="导入 ({count}/{total}) sprite",
                kind="script_unity_import",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约验收：1) task.output_paths 每个文件存在且 size > 0；2) 是合法 PNG（首 8 字节 == \\x89PNG\\r\\n\\x1a\\n）；"
                "3) 同名 .meta 文件已生成；"
                "4) **对每个图像文件调 verify_image_dimensions(file_path=<路径>, expected_width=task.output_schema.width, expected_height=task.output_schema.height)，返回 ok=false 直接 verdict=fail，issues 必须带实际 actual_width × actual_height 与契约尺寸的对比**。"
                "**不参考 Head spec 作为补充验收**——尺寸 source of truth 是 task.output_schema。"
                "**emit_output 的 payload 必须含 task.output_schema 里 required 列的全部字段**——本任务为 file_paths / width / height，缺一个 schema 校验就 fail。"
                "**Crew v5 fan-out 模式**：若 prev_step_payload 含 `results` 数组（N 个子 task 的 captured），逐项校验每个 sub-result.verdict；任一非 pass 则整体 verdict=fail，issues 汇总所有失败子的原因。"
                "调 emit_output(payload={'verdict': 'pass'|'fail', 'file_paths': [...], 'width': <契约值>, 'height': <契约值>, 'issues': [...], 'summary': '...'})。",
                step_role="qa",
                kind="script_qa",
                progress_template="验收 {n} 个 PNG",
            ),
        ],
    },
    # ── 3D Asset Crew ─────────────────────────────────────────────
    {
        "name": "3D 模型组",
        "applicable_scenarios": "**.fbx / .blend / .obj 三维模型专属**（3D 角色 / 道具 / 环境网格）。Blender MCP 建模。**禁止用于 .png 平面图 —— 那是 2D 美术资产组**。",
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
                "[脚本执行，不调 LLM] 按 task.detail 关键字映射 Unity ModelImporter："
                "meshCompression / isReadable / importNormals / animationType (None/Generic/Humanoid)。"
                "对每个 .fbx/.obj/.blend 调 manage_asset action=modify。",
                step_role="executor",
                progress_template="导入 ({count}/{total}) 模型",
                kind="script_unity_import",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约验收：1) 每个 .fbx 文件存在 + 非空；2) FBX 文件首部 magic 合法（首字符 'K' 或 binary FBX 头）；3) 同名 .meta 已生成。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                kind="script_qa",
                progress_template="验收 {n} 个 .fbx",
            ),
        ],
    },
    # ── Animation Crew ────────────────────────────────────────────
    {
        "name": "动画组",
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
                kind="script_qa",
                progress_template="验收 {n} 个动画",
            ),
        ],
    },
    # ── VFX Crew ──────────────────────────────────────────────────
    {
        "name": "特效组",
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
                kind="script_qa",
                progress_template="验收 VFX prefab",
            ),
        ],
    },
    # ── System Implementation Crew ────────────────────────────────
    {
        "name": "系统实现组",
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
                "按 PM **code_contract**（runtime 注入在「## 🔴 代码契约」块）+ Head spec 用 Unity MCP（create_script / script_apply_edits / apply_text_edits）创建 .cs 文件到 task.output_paths。"
                "**实现循环**（强制）："
                "(1) 先 create_script 把每个 .cs 文件骨架建好；"
                "(2) 用 script_apply_edits / apply_text_edits 把契约里的每个 signature 都实现进去，禁止 `// TODO` 占位、禁止 method body 留空、禁止漏写 event/property/method 任一种；"
                "(3) **逐条 find_in_file 自审**：对契约里列的每个 signature，调 find_in_file(path, signature) 验证字面存在；缺哪个回 (2) 补哪个；"
                "(4) 全部覆盖 + validate_script 通过 + Unity refresh 无编译错误，再 emit_output(payload={'file_paths': [...], 'coverage': {'<path>': <count>, ...}}) 报告。"
                "**如果你因 max_iter 提前停手 → 当前未覆盖的签名留给 QA 报 fail，整个 task 失败、下游阻塞**。",
                step_role="executor",
                progress_template="写脚本 ({count}/{total})",
                # LLM-bound; DeepSeek 单 API key 健康并发上限 ~3.
                fanout={"concurrency_cap": 3},
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM **code_contract**（runtime 注入）+ 文件存在性 双重验收："
                "1) 每个 .cs 文件存在 + .meta 齐全 + validate_script 通过；"
                "2) **对契约里列的每个 signature 调 find_in_file(path, signature)**，缺一个即 verdict='fail'，issues 必须列具体缺失符号（让 Debugger 能定位）。"
                "**Crew v5 fan-out 模式**：若 prev_step_payload 含 `results` 数组，逐项校验每个 sub-result.verdict；任一非 pass 则整体 verdict=fail，issues 汇总所有失败子的缺失符号。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                kind="script_qa",
                progress_template="验收 {n} 个 .cs",
            ),
        ],
    },
    # ── UI Implementation Crew ────────────────────────────────────
    {
        "name": "UI 实现组",
        "applicable_scenarios": "UI 界面（Canvas + Image + Text + Button，含 UI 图片）",
        "sequence": [
            _seq_step(
                "UI/UX Designer",
                "把 task.output_paths（UI Prefab + UI 图片路径）转化为 UI 规格：布局（Canvas size / 锚点 / 层级）、交互行为。"
                "**图片尺寸不要重定** —— 从 task.output_schema 读 width/height（PM 已定），你只补"
                "「每元素对应哪张图 + 在 Canvas 里怎么摆 + 交互」。"
                "调 emit_output(payload={'layout': ..., 'asset_mapping': ..., 'width': <from output_schema>, 'height': <from output_schema>, 'interactions': ...}) 提交。",
                step_role="head",
                progress_template="制定 UI 规格",
            ),
            _seq_step(
                "ComfyUI Image Generator",
                "对 task.output_paths 中的 UI 图片路径真生 PNG。"
                "**width/height 必须显式从 task.output_schema 读并传给 comfy_create_workflow_from_template params**（不是 Head spec）。"
                "生成后建议自调 verify_image_dimensions 校验一遍再 emit。"
                "调 emit_output(payload={'file_paths': [...], 'width': <契约值>, 'height': <契约值>}) 报告。",
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
                "对照 PM 契约验收："
                "1) UI prefab 完整性（manage_scene load 不抛 missing reference）；"
                "2) 图片 reference 解析 OK；"
                "3) .meta 齐全；"
                "4) **每个 UI 图片调 verify_image_dimensions(file_path=..., expected_width=task.output_schema.width, expected_height=task.output_schema.height)，ok=false → verdict=fail，issues 带实际 actual_w × actual_h**。"
                "**emit_output 的 payload 必须含 task.output_schema.required 全部字段（任务含图像 → 必带 width/height）**。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'width': <如有>, 'height': <如有>, 'issues': [...]})。",
                step_role="qa",
                kind="script_qa",
                progress_template="验收 UI prefab",
            ),
        ],
    },
    # ── Audio Crew ────────────────────────────────────────────────
    {
        "name": "音频组",
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
                # 8-bit synthesis is CPU-light + pure Python, safe to fan-out.
                fanout={"concurrency_cap": 3},
            ),
            _seq_step(
                "Unity Developer",
                "[脚本执行，不调 LLM] 按文件时长 + task.detail 关键字映射 Unity AudioImporter："
                "loadType (Streaming/DecompressOnLoad/CompressedInMemory) / "
                "compressionFormat (Vorbis/ADPCM) / forceToMono / preloadAudioData。"
                "对每个 .wav/.mp3/.ogg 调 manage_asset action=modify。"
                "AudioManager.cs 创建不在此步——属于系统实现组的活。",
                step_role="executor",
                progress_template="导入 ({count}/{total}) AudioClip",
                kind="script_unity_import",
            ),
            _seq_step(
                "QA Engineer",
                "对照 PM 契约：.wav 存在 + size > 44 字节（RIFF 头）+ RIFF/WAVE header 合法（首 4 字节 b'RIFF'、字节 8-12 b'WAVE'）+ .meta 齐全。"
                "**Crew v5 fan-out 模式**：若 prev_step_payload 含 `results` 数组，逐项校验每个 sub-result.verdict；任一非 pass 则整体 verdict=fail。"
                "调 emit_output(payload={'verdict': ..., 'file_paths': [...], 'issues': [...]})。",
                step_role="qa",
                kind="script_qa",
                progress_template="验收 {n} 个 wav",
            ),
        ],
    },
    # ── Scene Assembly Crew ───────────────────────────────────────
    {
        "name": "场景装配组",
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
                kind="script_qa",
                progress_template="验收场景",
            ),
        ],
    },
]


# ── Seeding entry ─────────────────────────────────────────────────

async def _ensure_agent(spec: dict, tool_name_to_id: dict[str, str],
                        llm_id_hint: str = "") -> str:
    """Insert or update a Crew-pool agent (matched by role); return its id.

    Existing agents get their tool_ids + goal/backstory **refreshed** to
    match the current seed. This is important: tool sets evolve across
    PM v4 stages (e.g., adding Unity MCP tools to Unity Developer in
    stage E), and a previously-seeded agent shouldn't be stuck with the
    older smaller set. Idempotent: same seed input → same DB row.
    """
    desired_tool_ids = _resolve_tools(tool_name_to_id, spec["tools"])
    desired_tool_ids_json = json.dumps(desired_tool_ids)

    existing = await crud.get_all(
        "agents", "role = ? AND is_auto_generated = 0", (spec["role"],),
    )
    if existing:
        row = existing[0]
        # **Diff-then-update**: only write if something actually changed.
        # Every boot used to UPDATE 14 rows even when content was
        # identical — combined with the 4MB WAL accumulated from earlier
        # test runs, that triggered "database is locked" on `_ensure_agent`
        # during PM v4 startup (incident 2026-05-16 14:20). The no-op
        # path avoids the write-lock churn entirely.
        existing_tool_ids = row.get("tool_ids") or "[]"
        if (row.get("goal") == spec["goal"]
                and row.get("backstory") == spec["backstory"]
                and existing_tool_ids == desired_tool_ids_json):
            return row["id"]
        await crud.update_by_id("agents", row["id"], {
            "goal": spec["goal"],
            "backstory": spec["backstory"],
            "tool_ids": desired_tool_ids_json,
        })
        log.info("seed.crew_agent_refreshed",
                 role=spec["role"], id=row["id"], n_tools=len(desired_tool_ids))
        return row["id"]

    row = await crud.insert("agents", {
        "role": spec["role"],
        "goal": spec["goal"],
        "backstory": spec["backstory"],
        "reasoning": 0,
        "max_retry": 2,
        "memory_enabled": 0,
        "memory_path": None,
        "thinking_mode": 0,
        "tool_ids": json.dumps(desired_tool_ids),
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


# Old → new name mapping for in-place rename. Existing project tasks
# reference Crews by id, not name, so renaming preserves all the
# user's saved projects (the 祖玛 crew_xxx ids stay valid). _rename_legacy_crews
# runs once per boot before the normal _ensure_crew loop; if the old
# name is gone (fresh install) it's a no-op.
_LEGACY_NAME_MAP: dict[str, str] = {
    "Art Crew": "2D 美术资产组",
    # 2026-05-19: rename "美术资产组" → "2D 美术资产组" so Phase 5
    # LLM can't confuse it with the 3D Crew (the bare "美术" prefix
    # routinely got "角色 sprite" tasks misrouted to Blender).
    "美术资产组": "2D 美术资产组",
    "3D Asset Crew": "3D 模型组",
    "Animation Crew": "动画组",
    "VFX Crew": "特效组",
    "System Implementation Crew": "系统实现组",
    "UI Implementation Crew": "UI 实现组",
    "Audio Crew": "音频组",
    "Scene Assembly Crew": "场景装配组",
}


async def _rename_legacy_crews() -> None:
    """In-place migration of legacy English-named Crews to their Chinese
    seed equivalents.

    Three cases per (old, new) pair:
      1. Neither row exists  → nothing to do.
      2. Only old exists     → rename in place (cheapest path).
      3. Both rows exist     → repoint every tasks.performer_id from old
         to new, then delete old. Without this branch the prior version
         silently SKIPPED, leaving duplicate Crews (the 24-row mess on
         2026-05-16 that scripts/cleanup_legacy_crews.py had to clean).
    """
    from infra.repo.sqlite_repo import get_db

    for old, new in _LEGACY_NAME_MAP.items():
        if old == new:
            continue
        old_rows = await crud.get_all("crews", "name = ?", (old,))
        if not old_rows:
            continue
        new_rows = await crud.get_all("crews", "name = ?", (new,))
        if not new_rows:
            # Simple rename — preserves crew id, so task refs stay valid.
            await crud.update_by_id("crews", old_rows[0]["id"], {"name": new})
            log.info("seed.crew_renamed",
                     id=old_rows[0]["id"], old=old, new=new)
            continue
        # Both exist: merge by repointing every task that referenced
        # the legacy crew to the seed crew, then drop the legacy row.
        old_id = old_rows[0]["id"]
        new_id = new_rows[0]["id"]
        db = await get_db()
        cursor = await db.execute(
            "UPDATE tasks SET performer_id = ? WHERE performer_id = ?",
            (new_id, old_id),
        )
        repointed = cursor.rowcount or 0
        await db.execute("DELETE FROM crews WHERE id = ?", (old_id,))
        await db.commit()
        log.info("seed.crew_merged",
                 old=old, old_id=old_id, new=new, new_id=new_id,
                 task_refs_repointed=repointed)


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

    # Migrate any legacy English-named Crews to their Chinese name
    # BEFORE the seed loop runs; otherwise the loop would see no row
    # matching the new name and INSERT a duplicate.
    await _rename_legacy_crews()

    role_to_agent_id: dict[str, str] = {}
    for agent_spec in SEED_AGENTS:
        aid = await _ensure_agent(agent_spec, tool_name_to_id, llm_id)
        role_to_agent_id[agent_spec["role"]] = aid

    crew_name_to_id: dict[str, str] = {}
    for crew_spec in SEED_CREWS:
        cid = await _ensure_crew(crew_spec, role_to_agent_id)
        crew_name_to_id[crew_spec["name"]] = cid

    # 2026-05-19: refresh applicable_scenarios + agent_sequence + agent_ids
    # on existing crew rows so prompt + sequence changes (e.g. dropping
    # Concept Artist from 2D Crew) actually reach the runtime. _ensure_crew
    # is INSERT-only; without this UPDATE pass, edits to SEED_CREWS only
    # take effect on a freshly seeded DB. Cheap idempotent rewrite.
    for crew_spec in SEED_CREWS:
        cid = crew_name_to_id.get(crew_spec["name"])
        if not cid:
            continue
        # Rebuild sequence + agent_ids using current role→id map. Skips
        # any step whose agent_role doesn't resolve (logs warning, doesn't
        # silently drop without notice — same _ensure_crew behavior).
        sequence: list[dict] = []
        agent_ids: list[str] = []
        for step in crew_spec["sequence"]:
            agent_role = step["agent_role"]
            agent_id = role_to_agent_id.get(agent_role)
            if not agent_id:
                log.warning("seed.crew_refresh_missing_agent",
                            crew=crew_spec["name"], role=agent_role)
                continue
            refreshed_step = {
                "role": step["role"],
                "agent_id": agent_id,
                "step_instructions": step["step_instructions"],
                "progress_template": step["progress_template"],
            }
            if step.get("fanout") is not None:
                refreshed_step["fanout"] = step["fanout"]
            if step.get("kind") is not None:
                refreshed_step["kind"] = step["kind"]
            sequence.append(refreshed_step)
            agent_ids.append(agent_id)
        await crud.update_by_id("crews", cid, {
            "applicable_scenarios": crew_spec["applicable_scenarios"],
            "agent_sequence": json.dumps(sequence, ensure_ascii=False),
            "agent_ids": json.dumps(agent_ids),
        })

    return crew_name_to_id
