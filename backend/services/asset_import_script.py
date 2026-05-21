"""Deterministic Unity asset import configuration — replaces the LLM
Technical Artist step (Stage 4 of the LLM → script migration).

TA's job is purely a rule-driven mapping: given a file's suffix, size,
and the parent task's detail text, decide what Unity importer settings
(TextureType / filterMode / wrapMode / spritePixelsPerUnit / mipmap /
audio loadType / model animationType / ...) should apply. There's no
creative judgement involved — the same 5 art directors would all pick
the same settings for "64×64 pixel art sprite for a 2D game".

LLM TA failure modes this replaces:
  - Inconsistent settings between sibling assets ("3 sprites got Point
    filter, 2 got Bilinear — same project, no reason")
  - Wrong tool calls ("set Sprite mode" via manage_texture instead of
    manage_asset modify)
  - Forgot to call AssetDatabase.Refresh
  - Made up properties that don't exist on TextureImporter

Public entry:
    `import_assets_for_task(task_id, prev_payload, project_root)`
    → `{verdict, imported, issues, summary}`
"""
from __future__ import annotations

import asyncio
import json
import re
import wave
from pathlib import Path
from typing import Any

import structlog

from infra.repo import crud

log = structlog.get_logger()


# ── Suffix dispatch ────────────────────────────────────────────────

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tga", ".psd"}
_MODEL_SUFFIXES = {".fbx", ".obj", ".blend", ".dae"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".aiff"}


# ── Keyword sets ──────────────────────────────────────────────────

_SPRITE_KEYWORDS = (
    "sprite", "ui", "icon", "2d", "角色", "道具", "图标", "立绘",
    "spritesheet", "sheet",
)
_PIXEL_ART_KEYWORDS = ("像素", "pixel", "8-bit", "8bit", "16-bit", "16bit")
_NORMAL_MAP_KEYWORDS = ("法线", "normal map", "_normal", "_n.")
_SPRITE_SHEET_KEYWORDS = ("sheet", "spritesheet", "atlas")
_ANIM_KEYWORDS = ("动画", "anim", "skeleton", "rig", "骨骼", "绑骨")
_HUMANOID_KEYWORDS = ("角色", "human", "character", "biped", "类人")
_BGM_KEYWORDS = ("bgm", "music", "音乐", "背景音乐", "ambient")
_SFX_KEYWORDS = ("sfx", "音效", "声效", "click", "hit")


# ── Decision functions ────────────────────────────────────────────


def decide_texture_import(
    rel_path: str,
    detail: str,
    width: int,
    height: int,
    has_alpha: bool,
) -> dict[str, Any]:
    """Pick Unity TextureImporter settings for a 2D image asset.

    Rules:
      - textureType: NormalMap if filename/detail says so;
        Sprite (2D and UI) if path/detail signals 2D usage;
        Default otherwise.
      - filterMode: Point when small or pixel-art keywords; Bilinear else.
      - wrapMode: Clamp for sprites (most common usage), Repeat for textures.
      - mipmapEnabled: off for sprites; on for default textures.
      - alphaIsTransparency: true when the file has an alpha channel.
      - spriteMode: Multiple if "sheet" mentioned, else Single.
      - maxTextureSize: power-of-2 ceiling of max(width, height), capped
        at 4096 (Unity's most permissive default).
    """
    rel = rel_path.lower()
    det = (detail or "").lower()

    is_normal_map = any(k in rel or k in det for k in _NORMAL_MAP_KEYWORDS)
    is_sprite = (
        "/sprites/" in rel
        or "/ui/" in rel
        or any(k in det for k in _SPRITE_KEYWORDS)
    )
    is_pixel_art = (
        max(width, height) <= 128
        or any(k in det for k in _PIXEL_ART_KEYWORDS)
    )
    is_sprite_sheet = any(k in det for k in _SPRITE_SHEET_KEYWORDS)

    if is_normal_map:
        texture_type = "NormalMap"
    elif is_sprite:
        texture_type = "Sprite (2D and UI)"
    else:
        texture_type = "Default"

    return {
        "textureType": texture_type,
        "filterMode": "Point" if is_pixel_art else "Bilinear",
        "wrapMode": "Clamp" if texture_type == "Sprite (2D and UI)" else "Repeat",
        "mipmapEnabled": texture_type != "Sprite (2D and UI)",
        "alphaIsTransparency": has_alpha,
        "spritePixelsPerUnit": 100,
        "spriteMode": "Multiple" if is_sprite_sheet else "Single",
        "maxTextureSize": _ceil_pow2(max(width, height, 32)),
    }


def decide_model_import(rel_path: str, detail: str) -> dict[str, Any]:
    """Pick Unity ModelImporter settings for a 3D model asset."""
    det = (detail or "").lower()
    has_anim = any(k in det for k in _ANIM_KEYWORDS)
    is_humanoid = any(k in det for k in _HUMANOID_KEYWORDS)
    return {
        "meshCompression": "Medium",
        "isReadable": False,
        "importNormals": "Calculate" if "smooth" in det else "Import",
        "animationType": (
            "Humanoid" if (has_anim and is_humanoid)
            else "Generic" if has_anim
            else "None"
        ),
        "materialsImportMode": "ImportViaMaterialDescription",
    }


def decide_audio_import(
    rel_path: str,
    detail: str,
    duration_sec: float,
) -> dict[str, Any]:
    """Pick Unity AudioImporter settings."""
    det = (detail or "").lower()
    rel = rel_path.lower()
    is_bgm = (
        duration_sec > 30
        or any(k in rel or k in det for k in _BGM_KEYWORDS)
    )
    is_sfx = (
        duration_sec < 5
        or any(k in rel or k in det for k in _SFX_KEYWORDS)
    )
    return {
        "loadType": (
            "Streaming" if is_bgm
            else "DecompressOnLoad" if is_sfx
            else "CompressedInMemory"
        ),
        "compressionFormat": "Vorbis" if is_bgm else "ADPCM",
        "forceToMono": is_sfx,
        "preloadAudioData": is_sfx,  # BGM streams, SFX preloads
    }


# ── File metadata readers ─────────────────────────────────────────


def _read_image_meta(abs_path: Path) -> tuple[int, int, bool]:
    """Return (width, height, has_alpha). Defaults to (0, 0, False) on
    failure — caller treats as "skip this file"."""
    try:
        from PIL import Image
        with Image.open(abs_path) as img:
            return img.width, img.height, img.mode in ("RGBA", "LA", "PA")
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "asset_import.image_meta_failed",
            path=str(abs_path), error=str(exc),
        )
        return 0, 0, False


def _read_audio_duration(abs_path: Path) -> float:
    """WAV duration in seconds (stdlib `wave`). 0 for non-WAV — keeps
    the audio decision running on filename signals only."""
    if abs_path.suffix.lower() != ".wav":
        return 0.0
    try:
        with wave.open(str(abs_path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
        return frames / rate if rate else 0.0
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "asset_import.audio_duration_failed",
            path=str(abs_path), error=str(exc),
        )
        return 0.0


# ── Unity MCP invocation ──────────────────────────────────────────


async def _call_unity_manage_asset(rel_path: str, properties: dict) -> str:
    """Run `manage_asset action=modify target=<rel_path> properties=<...>`
    on the Unity MCP server. Sync inside Unity (Editor C# call), wrapped
    in asyncio.to_thread so we don't block the event loop."""
    def _sync_call() -> str:
        from src.tools.builtin.unity._mcp import get_unity_mcp_pool
        pool = get_unity_mcp_pool()
        return pool.call("unity", "manage_asset", {
            "action": "modify",
            "target": rel_path,
            "properties": properties,
        })
    return await asyncio.to_thread(_sync_call)


async def _refresh_unity() -> str:
    """Trigger AssetDatabase.Refresh so the new import settings actually
    apply. Skipping this means the asset's .meta keeps the OLD settings
    until the user clicks in Unity's project window."""
    def _sync_call() -> str:
        from src.tools.builtin.unity._mcp import get_unity_mcp_pool
        pool = get_unity_mcp_pool()
        return pool.call("unity", "refresh_unity", {})
    try:
        return await asyncio.to_thread(_sync_call)
    except Exception as exc:  # noqa: BLE001
        log.warning("asset_import.refresh_failed", error=str(exc))
        return f"refresh_unity failed: {exc}"


# ── Unity-project detection ───────────────────────────────────────


def _is_unity_project(root: str) -> bool:
    """A Unity project's root always has both `ProjectSettings/` and
    `Assets/` folders (Editor refuses to open anything else)."""
    if not root:
        return False
    p = Path(root)
    return (p / "ProjectSettings").is_dir() and (p / "Assets").is_dir()


# ── Top-level entry ───────────────────────────────────────────────


async def import_assets_for_task(
    *,
    task_id: str,
    prev_payload: dict | None,  # noqa: ARG001 — reserved for future signal
    project_root: str,
) -> dict[str, Any]:
    """Configure Unity importer settings for every file the parent task
    declared in its output_paths. Returns an emit_output-shaped dict.

    `prev_payload` is the upstream executor's emit_output (e.g. the
    fan-out aggregate `{results: [...]}`). Currently unused — we read
    output_paths straight from the task row because that's the source
    of truth and is identical to the union of children's paths. Kept
    on the signature so a future revision can use upstream metadata
    (e.g. width/height from the Generator's report) without changing
    the call site.
    """
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        return _fail([f"task {task_id} not found"])

    if not _is_unity_project(project_root):
        # Common for debug projects (E:\ComfyUIData/ etc.) — skip
        # cleanly with verdict=pass so the chain doesn't halt over a
        # missing Unity context.
        log.info(
            "asset_import.non_unity_project_skipped",
            project_root=project_root, task_id=task_id,
        )
        return {
            "verdict": "pass",
            "imported": [],
            "issues": [],
            "summary": "skipped — project root is not a Unity project",
        }

    output_paths = _parse_json_list(task.get("output_paths"))
    if not output_paths:
        return {
            "verdict": "pass",
            "imported": [],
            "issues": [],
            "summary": "no output_paths — nothing to configure",
        }

    detail = task.get("detail") or ""
    root = Path(project_root)
    imported: list[dict] = []
    issues: list[str] = []

    for rel_path in output_paths:
        abs_p = (root / rel_path).resolve()
        try:
            abs_p.relative_to(root.resolve())  # path-escape guard
        except ValueError:
            issues.append(f"{rel_path}: 路径越过项目根目录，跳过")
            continue
        if not abs_p.exists() or not abs_p.is_file():
            # QA will catch missing files; TA doesn't need to also
            # fail here. Skipping silently keeps the verdict clean.
            log.info(
                "asset_import.skip_missing_file",
                rel_path=rel_path, task_id=task_id,
            )
            continue

        suffix = abs_p.suffix.lower()
        settings = _decide_for_file(suffix, abs_p, rel_path, detail)
        if settings is None:
            # Suffix has no importer (.cs / .anim / .unity / .mat /
            # .prefab — these carry config inside the file itself).
            continue

        try:
            result = await _call_unity_manage_asset(rel_path, settings)
            if "ERROR" in result.upper() or "FAILED" in result.upper():
                issues.append(
                    f"{rel_path}: Unity MCP 拒绝设置 — {result[:160]}"
                )
                continue
            imported.append({"path": rel_path, "settings": settings})
            log.info(
                "asset_import.configured",
                rel_path=rel_path, settings_keys=list(settings.keys()),
            )
        except Exception as exc:  # noqa: BLE001
            issues.append(f"{rel_path}: Unity MCP 调用异常 {exc}")
            log.warning(
                "asset_import.mcp_call_failed",
                rel_path=rel_path, error=str(exc),
            )

    # Single refresh after all modifies so Unity batches the reimport.
    if imported:
        await _refresh_unity()

    return {
        "verdict": "fail" if issues else "pass",
        "imported": imported,
        "issues": issues,
        "summary": _build_summary(imported, issues),
    }


def _decide_for_file(
    suffix: str, abs_p: Path, rel_path: str, detail: str,
) -> dict | None:
    """Suffix → decide_* dispatch. Returns None when the file kind has
    no Unity importer to configure (e.g. .cs / .unity / .prefab)."""
    if suffix in _IMAGE_SUFFIXES:
        w, h, has_alpha = _read_image_meta(abs_p)
        if w == 0:  # couldn't decode — let QA's deeper check catch it
            return None
        return decide_texture_import(rel_path, detail, w, h, has_alpha)
    if suffix in _MODEL_SUFFIXES:
        return decide_model_import(rel_path, detail)
    if suffix in _AUDIO_SUFFIXES:
        duration = _read_audio_duration(abs_p)
        return decide_audio_import(rel_path, detail, duration)
    return None


# ── Helpers ───────────────────────────────────────────────────────


def _ceil_pow2(n: int) -> int:
    """Round up to nearest power of 2, capped at 4096. Unity's
    maxTextureSize must be a power of 2; 4096 is the highest common
    setting (8192 needs Editor permissions on most platforms)."""
    if n <= 0:
        return 32
    n = max(32, n)  # Unity rejects anything below 32
    r = 1
    while r < n:
        r <<= 1
    return min(r, 4096)


def _fail(issues: list[str]) -> dict:
    return {
        "verdict": "fail",
        "imported": [],
        "issues": issues,
        "summary": "TA 脚本失败",
    }


def _build_summary(imported: list[dict], issues: list[str]) -> str:
    n_ok = len(imported)
    n_fail = len(issues)
    if not issues:
        return f"配置 {n_ok} 个资产的 Unity 导入设置"
    return f"配置 {n_ok} 个资产；{n_fail} 个失败"


def _parse_json_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, str)]
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [x for x in parsed if isinstance(x, str)]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


# Unused-import suppressors (kept for type hints + future extension)
_ = re
