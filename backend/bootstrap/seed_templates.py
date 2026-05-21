"""Seed the `templates` table — one source of truth for per-scenario
project templates.

Idempotent: existing rows (matched by id) are UPDATEd only when their
content actually changed. New rows are INSERTed. No-op for rows already
up-to-date — same diff-then-write pattern as `_ensure_agent` so a
backend boot doesn't churn the WAL.

Adding a new template
---------------------
Add an entry to `TEMPLATE_SEEDS` below. The next backend restart picks
it up. No migration needed.

Categories use the same enum the home toggle does:
  'unity'    — existing Unity Universal2D / 3D / AR / MR
  'ai_video' — AI 漫剧剧本 / AI 短剧分镜 / ...
  'ppt'      — 自动化 PPT 演示稿 / 商业提案 / ...
"""
from __future__ import annotations

import json

import structlog

from infra.repo import crud

log = structlog.get_logger()


# ── Template seed registry ───────────────────────────────────────────
# Each entry maps to one row in the `templates` table. Keep the id
# stable across restarts — `projects.template_id` references it.
TEMPLATE_SEEDS: list[dict] = [
    # ── Unity 模板 ──────────────────────────────────────────────
    {
        "id": "unity_universal_2d",
        "category": "unity",
        "name": "Unity 通用 2D",
        "description": "通用 2D Unity 项目（俯视 / 横版 / 卡牌 / 解谜 etc.）",
        "scaffold_strategy": "git_clone",
        "scaffold_config": {
            "repo": "https://github.com/Joe-Hank/Templates.git",
            "sub_dir": "Universal2D",
        },
        "inception_prompt_id": "unity_default",
        "seed_crew_names": [
            "2D 美术资产组", "3D 模型组", "动画组", "特效组",
            "系统实现组", "UI 实现组", "音频组", "场景装配组",
        ],
    },
    {
        "id": "unity_universal_3d",
        "category": "unity",
        "name": "Unity 通用 3D",
        "description": "通用 3D Unity 项目（FPS / TPS / 平台跳跃 / 模拟经营 etc.）",
        "scaffold_strategy": "git_clone",
        "scaffold_config": {
            "repo": "https://github.com/Joe-Hank/Templates.git",
            "sub_dir": "Universal3D",
        },
        "inception_prompt_id": "unity_default",
        "seed_crew_names": [
            "2D 美术资产组", "3D 模型组", "动画组", "特效组",
            "系统实现组", "UI 实现组", "音频组", "场景装配组",
        ],
    },
    {
        "id": "unity_ar_mobile",
        "category": "unity",
        "name": "Unity AR 移动端",
        "description": "AR Foundation 移动端项目（手机 AR 体验）",
        "scaffold_strategy": "git_clone",
        "scaffold_config": {
            "repo": "https://github.com/Joe-Hank/Templates.git",
            "sub_dir": "ARMobile",
        },
        "inception_prompt_id": "unity_default",
        "seed_crew_names": [
            "2D 美术资产组", "3D 模型组", "动画组", "特效组",
            "系统实现组", "UI 实现组", "音频组", "场景装配组",
        ],
    },
    {
        "id": "unity_mr_core",
        "category": "unity",
        "name": "Unity MR 核心",
        "description": "OpenXR / Meta XR MR 项目（Quest / Vision Pro 等头显）",
        "scaffold_strategy": "git_clone",
        "scaffold_config": {
            "repo": "https://github.com/Joe-Hank/Templates.git",
            "sub_dir": "MRCore",
        },
        "inception_prompt_id": "unity_default",
        "seed_crew_names": [
            "2D 美术资产组", "3D 模型组", "动画组", "特效组",
            "系统实现组", "UI 实现组", "音频组", "场景装配组",
        ],
    },

    # ── AI 视频模板（Phase B 落地）────────────────────────────
    {
        "id": "aivideo_manga_v1",
        "category": "ai_video",
        "name": "AI 漫剧剧本",
        "description": (
            "多 agent 协作产出漫剧剧本：故事大纲 → 角色设定 → 分集分镜 → 完整对白稿。"
            "纯文本产出，适合 CrewAI 跑稳的轻量化场景。"
        ),
        # 不需要 git clone；本地建一个工作目录就行
        "scaffold_strategy": "local_mkdir",
        "scaffold_config": {
            "subdirs": ["story", "characters", "scenes", "scripts"],
        },
        "inception_prompt_id": "aivideo_manga_default",
        # Crew 名称按 Phase B 落地后实际 seed 的名字填
        "seed_crew_names": [
            "故事大纲组", "角色设定组", "分集创作组", "整稿 QA 组",
        ],
    },
]


def _to_db_row(spec: dict) -> dict:
    """Spec dict → DB row dict. JSON-encode the structured fields."""
    return {
        "id": spec["id"],
        "category": spec["category"],
        "name": spec["name"],
        "description": spec.get("description") or "",
        "scaffold_strategy": spec["scaffold_strategy"],
        "scaffold_config": json.dumps(
            spec.get("scaffold_config") or {}, ensure_ascii=False,
        ),
        "inception_prompt_id": spec.get("inception_prompt_id") or "",
        "seed_crew_names": json.dumps(
            spec.get("seed_crew_names") or [], ensure_ascii=False,
        ),
        "is_active": 1,
    }


async def ensure_templates() -> None:
    """Idempotent: insert missing templates, refresh changed ones, noop the rest."""
    n_created = 0
    n_refreshed = 0
    n_noop = 0
    for spec in TEMPLATE_SEEDS:
        desired = _to_db_row(spec)
        existing = await crud.get_by_id("templates", spec["id"])
        if existing is None:
            # `desired["id"]` is already set deterministically (e.g.
            # "unity_universal_2d"); crud.insert honours pre-set ids.
            await crud.insert("templates", desired)
            n_created += 1
            log.info("seed.template_created", id=spec["id"],
                     category=spec["category"], name=spec["name"])
            continue
        # Diff-then-update: only write if content drifted
        drift = any(
            existing.get(k) != desired[k]
            for k in ("category", "name", "description", "scaffold_strategy",
                      "scaffold_config", "inception_prompt_id",
                      "seed_crew_names", "is_active")
        )
        if drift:
            update_fields = {
                k: desired[k]
                for k in ("category", "name", "description", "scaffold_strategy",
                          "scaffold_config", "inception_prompt_id",
                          "seed_crew_names", "is_active")
            }
            await crud.update_by_id("templates", spec["id"], update_fields)
            n_refreshed += 1
            log.info("seed.template_refreshed", id=spec["id"])
        else:
            n_noop += 1
    log.info("seed.templates_complete",
             created=n_created, refreshed=n_refreshed, noop=n_noop,
             total=len(TEMPLATE_SEEDS))
