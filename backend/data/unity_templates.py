"""Unity project templates — catalog Plan Maker reads in creation mode.

Scanned from real Unity Hub templates living under `E:\\UnityTemplate\\`
(Universal 2D / Universal 3D / AR Mobile / MR Core) plus a synthetic
"blank" template for non-Unity projects.

When the user picks a template the drawer pre-bakes `template_id` onto
the inception session; Plan Maker renders the template block into its
backstory and designs tasks that fit the directory + package layout.

To regenerate after Unity Hub updates: re-scan
`E:\\UnityTemplate\\<TemplateName>\\{Assets,Packages/manifest.json}` and
update the `directory_skeleton` + `default_packages` entries below.
The IDs and labels are intentionally stable so existing project rows
that reference them keep working.
"""
from __future__ import annotations

from typing import Any


UNITY_TEMPLATES: list[dict[str, Any]] = [
    # ── Universal 2D — Unity Hub "2D" template ─────────────────────
    {
        "id": "unity_universal_2d",
        "label": "Universal 2D",
        "description": "Unity 官方 2D 通用模板，适合平台跳跃、解谜、视觉小说、回合制 RPG 等",
        "kind": "unity",
        "render_pipeline": "（默认 Built-in，未启用 URP）",
        "input_system": "Legacy Input Manager（可选切换至 New Input System）",
        # Real shipped structure is minimal — Plan Maker should treat
        # below as "starter dirs + suggested places for new code".
        "directory_skeleton": [
            "Assets/Scenes/",         # ships with SampleScene.unity
            "Assets/Scripts/",        # 推荐：核心系统与控制器
            "Assets/Sprites/",        # 推荐：角色 / 物件 / UI 图
            "Assets/Animations/",     # 推荐：Animator + Clip
            "Assets/Prefabs/",        # 推荐：可复用对象
            "Assets/Audio/",          # 推荐：BGM / SFX
            "Assets/ScriptableObjects/",  # 推荐：数据资产
            "Assets/Fonts/",          # 预置：常用中文字体（中文文本直接引用）
        ],
        "default_packages": [
            "com.unity.feature.2d",
            "com.unity.textmeshpro",
            "com.unity.timeline",
            "com.unity.ugui",
            "com.unity.visualscripting",
        ],
    },

    # ── Universal 3D — Unity Hub "3D" template ─────────────────────
    {
        "id": "unity_universal_3d",
        "label": "Universal 3D",
        "description": "Unity 官方 3D 通用模板，适合第一/第三人称、模拟、休闲 3D 等",
        "kind": "unity",
        "render_pipeline": "（默认 Built-in，未启用 URP/HDRP）",
        "input_system": "Legacy Input Manager（可选切换至 New Input System）",
        "directory_skeleton": [
            "Assets/Scenes/",         # ships with SampleScene.unity
            "Assets/Scripts/",        # 推荐：核心系统 + Player + UI 控制
            "Assets/Models/",         # 推荐：FBX / OBJ
            "Assets/Materials/",      # 推荐：Material + Shader
            "Assets/Textures/",       # 推荐：贴图
            "Assets/Prefabs/",        # 推荐：可复用对象
            "Assets/Animations/",     # 推荐：Animator + Clip
            "Assets/Audio/",          # 推荐：BGM / SFX
            "Assets/Fonts/",          # 预置：常用中文字体（中文文本直接引用）
        ],
        "default_packages": [
            "com.unity.feature.development",
            "com.unity.textmeshpro",
            "com.unity.timeline",
            "com.unity.ugui",
            "com.unity.visualscripting",
        ],
    },

    # ── AR Mobile — Unity Hub "AR Mobile" template ─────────────────
    {
        "id": "unity_ar_mobile",
        "label": "AR Mobile",
        "description": "移动 AR（ARCore / ARKit）模板，含 AR Foundation + XR Interaction Toolkit 示例",
        "kind": "unity",
        "render_pipeline": "Universal Render Pipeline",
        "input_system": "New Input System (XR profile)",
        # Real shipped structure
        "directory_skeleton": [
            "Assets/Scenes/",                           # 默认 AR 启动场景
            "Assets/MobileARTemplateAssets/Prefabs/",   # AR 交互预制体
            "Assets/MobileARTemplateAssets/Scripts/",   # AR 行为脚本
            "Assets/MobileARTemplateAssets/Materials/", # AR 可视化材质
            "Assets/MobileARTemplateAssets/Shaders/",   # AR shader
            "Assets/MobileARTemplateAssets/UI/",        # AR UI 元素
            "Assets/MobileARTemplateAssets/AffordanceThemes/",  # 交互反馈主题
            "Assets/Samples/XR Interaction Toolkit/",   # XR 交互样例
            "Assets/Settings/Project Configuration/",   # 项目配置资产
            "Assets/XR/Settings/",                      # XR 设置
            "Assets/XRI/Settings/",                     # XR Interaction Toolkit 设置
            "Assets/TextMesh Pro/",                     # TMP 资源
            # 推荐新建：
            "Assets/Scripts/",                          # 推荐：你的业务脚本
            "Assets/Prefabs/",                          # 推荐：自定义 prefab
            "Assets/Fonts/",                            # 预置：常用中文字体（中文文本直接引用）
        ],
        "default_packages": [
            "com.unity.xr.arfoundation",
            "com.unity.xr.arcore",
            "com.unity.xr.arkit",
            "com.unity.xr.interaction.toolkit",
            "com.unity.xr.management",
            "com.unity.render-pipelines.universal",
            "com.unity.inputsystem",
            "com.unity.textmeshpro",
        ],
    },

    # ── MR Core — Unity Hub "MR Core" template ─────────────────────
    {
        "id": "unity_mr_core",
        "label": "MR Core",
        "description": "混合现实模板（Quest / Meta OpenXR），含 XR Hands + XR Interaction Toolkit",
        "kind": "unity",
        "render_pipeline": "Universal Render Pipeline",
        "input_system": "New Input System (XR profile)",
        "directory_skeleton": [
            "Assets/Scenes/",                       # 默认 MR 启动场景
            "Assets/MRTemplateAssets/Prefabs/",     # MR 交互预制体（含手部）
            "Assets/MRTemplateAssets/Scripts/",     # MR 行为脚本
            "Assets/MRTemplateAssets/Models/",      # MR 3D 模型
            "Assets/MRTemplateAssets/Materials/",   # 材质
            "Assets/MRTemplateAssets/Shaders/",     # shader
            "Assets/MRTemplateAssets/Audio/",       # 空间音频
            "Assets/MRTemplateAssets/Themes/",      # 交互反馈主题
            "Assets/MRTemplateAssets/Datums/",      # 数据配置
            "Assets/MRTemplateAssets/Sprites/",     # UI sprite
            "Assets/MRTemplateAssets/Videos/",      # 教学视频
            "Assets/MRTemplateAssets/Fonts/",       # 字体
            "Assets/Samples/XR Hands/",             # XR Hands 示例
            "Assets/Samples/XR Interaction Toolkit/",
            "Assets/Settings/Project Configuration/",
            "Assets/XR/Settings/",
            "Assets/XRI/Settings/",
            "Assets/TextMesh Pro/",
            # 推荐新建：
            "Assets/Scripts/",
            "Assets/Prefabs/",
            "Assets/Fonts/",                        # 预置：常用中文字体（中文文本直接引用，与 MRTemplateAssets/Fonts 并存）
        ],
        "default_packages": [
            "com.unity.xr.openxr",
            "com.unity.xr.meta-openxr",
            "com.unity.xr.hands",
            "com.unity.xr.interaction.toolkit",
            "com.unity.xr.management",
            "com.unity.xr.arfoundation",
            "com.unity.render-pipelines.universal",
            "com.unity.inputsystem",
            "com.unity.textmeshpro",
        ],
    },

    # ── Blank — for non-Unity / unconstrained projects ─────────────
    # Plan Maker currently still follows Unity defaults when this is
    # chosen (see project_polish_round followups). Real handling is on
    # the backlog: detect target stack from user intent + relax the
    # Unity-only assumptions.
    {
        "id": "blank",
        "label": "空模板（非 Unity / 通用）",
        "description": "不绑定 Unity，由 Plan Maker 与用户讨论后决定技术栈。"
                       "目前仍按 Unity 思路设计，未来会改为通用",
        "kind": "blank",
        "render_pipeline": "（无 — 由项目类型决定）",
        "input_system": "（无 — 由项目类型决定）",
        # Empty skeleton — Plan Maker will discuss with user and decide
        # paths/folders during planning. No starter assets enforced.
        "directory_skeleton": [],
        "default_packages": [],
    },
]


def get_template(template_id: str) -> dict[str, Any] | None:
    for t in UNITY_TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


def list_templates() -> list[dict[str, Any]]:
    return list(UNITY_TEMPLATES)


def render_template_context(template_id: str) -> str:
    """Render a template into a Plan Maker prompt section. Returns "" if
    the id is unknown so the caller can fall back gracefully.

    The "blank" template renders a different block — it tells Plan Maker
    that the project may not be Unity at all and to negotiate the stack
    with the user before assuming defaults."""
    t = get_template(template_id)
    if not t:
        return ""

    if t.get("kind") == "blank":
        return (
            f"## 项目模板: {t['label']}\n"
            f"{t['description']}\n\n"
            "**注意：用户选了空模板。**\n"
            "- 这可能是 Unity 项目，也可能是 Web / Python / CLI 工具 / 数据脚本等\n"
            "- **当前实现：暂时仍按 Unity 思路设计**（已记录待完善）\n"
            "- 未来：与用户讨论后决定栈再设计任务\n"
        )

    lines = [
        f"## 项目模板: {t['label']}",
        f"{t['description']}",
        f"渲染管线: {t['render_pipeline']}",
        f"输入系统: {t['input_system']}",
        "",
        "预期目录结构（含模板自带 + 推荐新建）:",
    ]
    for d in t["directory_skeleton"]:
        lines.append(f"  - {d}")
    lines.append("")
    lines.append("默认包（manifest.json 已包含）:")
    for p in t["default_packages"]:
        lines.append(f"  - {p}")
    # ── 项目级预置（所有 Unity 模板共享）─────────────────────────
    lines.extend([
        "",
        "项目预置环境:",
        "  - **MCP for Unity 已接入**：可直接调用 Unity 编辑器（读写资产 / 执行 C# / 查询场景 / 截图）。"
        "Unity 操作类 agent 优先用 MCP for Unity 的工具，而不是裸 write_file。",
        "  - **Assets/Fonts/ 内已预置常用中文字体**：所有需要中文显示的 TMP/UGUI 文本，"
        "直接引用该目录下的字体即可，不需要再下载/生成。",
    ])
    return "\n".join(lines)
