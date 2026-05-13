"""Unity project templates — static catalog for Plan Maker creation mode.

Each entry mirrors a real Unity Hub template. When the user picks one in
the first-round inception choice, Plan Maker renders the template's
directory_skeleton + default_packages into its backstory as the "what the
project will look like" context, then designs tasks that fit that layout.

This catalog is intentionally a flat Python list (not JSON) so it's
type-checkable, importable from anywhere, and trivial to extend. Future
work: support user-defined custom templates loaded from disk.
"""
from __future__ import annotations

from typing import Any


UNITY_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "unity_2d_urp",
        "label": "2D（URP 通用渲染管线）",
        "description": "适合 2D 平台跳跃、解谜、视觉小说、回合制 RPG 等",
        "render_pipeline": "Universal Render Pipeline",
        "input_system": "New Input System",
        "directory_skeleton": [
            "Assets/Scripts/Core/",
            "Assets/Scripts/UI/",
            "Assets/Scripts/Data/",
            "Assets/Sprites/",
            "Assets/Prefabs/",
            "Assets/Scenes/",
            "Assets/Audio/BGM/",
            "Assets/Audio/SFX/",
            "Assets/ScriptableObjects/",
            "Assets/Materials/",
            "Assets/Settings/",
        ],
        "default_packages": [
            "2D Sprite", "2D Tilemap Editor", "Input System",
            "TextMeshPro", "Universal RP",
        ],
    },
    {
        "id": "unity_3d_urp",
        "label": "3D（URP 通用渲染管线）",
        "description": "适合 3D 第一/第三人称、模拟、休闲 3D",
        "render_pipeline": "Universal Render Pipeline",
        "input_system": "New Input System",
        "directory_skeleton": [
            "Assets/Scripts/Core/",
            "Assets/Scripts/UI/",
            "Assets/Scripts/Player/",
            "Assets/Models/",
            "Assets/Materials/",
            "Assets/Textures/",
            "Assets/Prefabs/",
            "Assets/Scenes/",
            "Assets/Audio/BGM/",
            "Assets/Audio/SFX/",
            "Assets/Animations/",
            "Assets/Settings/",
        ],
        "default_packages": [
            "Input System", "Cinemachine", "TextMeshPro",
            "Universal RP", "ProBuilder",
        ],
    },
    {
        "id": "unity_3d_hdrp",
        "label": "3D HDRP（高保真渲染）",
        "description": "主机/PC 高画质 3D，需要写实光照与后处理",
        "render_pipeline": "High Definition Render Pipeline",
        "input_system": "New Input System",
        "directory_skeleton": [
            "Assets/Scripts/Core/",
            "Assets/Scripts/UI/",
            "Assets/Scripts/Player/",
            "Assets/Models/",
            "Assets/Materials/",
            "Assets/Textures/",
            "Assets/Lighting/",
            "Assets/Prefabs/",
            "Assets/Scenes/",
            "Assets/Audio/",
            "Assets/Animations/",
            "Assets/PostProcessing/",
            "Assets/Settings/",
        ],
        "default_packages": [
            "High Definition RP", "Input System", "Cinemachine",
            "ProBuilder", "TextMeshPro",
        ],
    },
    {
        "id": "unity_xr",
        "label": "Unity XR（VR / AR）",
        "description": "Quest、HoloLens、ARCore、ARKit 等 XR 平台",
        "render_pipeline": "Universal Render Pipeline",
        "input_system": "New Input System (XR profile)",
        "directory_skeleton": [
            "Assets/Scripts/XR/",
            "Assets/Scripts/UI/",
            "Assets/Prefabs/XR/",
            "Assets/Models/",
            "Assets/Materials/",
            "Assets/Scenes/",
            "Assets/Audio/",
            "Assets/Settings/XR/",
        ],
        "default_packages": [
            "XR Plugin Management", "XR Interaction Toolkit",
            "OpenXR Plugin", "Input System", "Universal RP",
        ],
    },
    {
        "id": "unity_mobile_2d",
        "label": "Mobile 2D（移动端 2D）",
        "description": "为 Android / iOS 优化的 2D 项目，含触屏输入与移动通知",
        "render_pipeline": "Universal Render Pipeline (Mobile profile)",
        "input_system": "New Input System (Touch)",
        "directory_skeleton": [
            "Assets/Scripts/Core/",
            "Assets/Scripts/UI/",
            "Assets/Scripts/Data/",
            "Assets/Sprites/",
            "Assets/Prefabs/",
            "Assets/Scenes/",
            "Assets/Audio/",
            "Assets/ScriptableObjects/",
            "Assets/Settings/Mobile/",
        ],
        "default_packages": [
            "2D Sprite", "Input System", "Universal RP",
            "Mobile Notifications", "TextMeshPro",
        ],
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
    the id is unknown so the caller can fall back gracefully."""
    t = get_template(template_id)
    if not t:
        return ""
    lines = [
        f"## 项目模板: {t['label']}",
        f"用途: {t['description']}",
        f"渲染管线: {t['render_pipeline']}",
        f"输入系统: {t['input_system']}",
        "",
        "预期目录结构:",
    ]
    for d in t["directory_skeleton"]:
        lines.append(f"  - {d}")
    lines.append("")
    lines.append("默认包:")
    for p in t["default_packages"]:
        lines.append(f"  - {p}")
    return "\n".join(lines)
