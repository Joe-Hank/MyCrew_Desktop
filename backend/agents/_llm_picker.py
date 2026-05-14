"""LLM 三档偏好选择：cheap / default / pro.

每个 sub-agent 在自己的 DEFAULT_PARAMS 里声明偏好。dispatcher 通过
pick_llm 解析出实际要用的 (provider_row, model_name)。

app_settings 两个可选 key：
  - cheap_llm  → 形如 "prov_xxx:flash-model" — 极便宜模型（合规门/分类器）
  - pro_llm    → 形如 "prov_xxx:pro-model"   — 强模型（架构设计/精确 op）

未配置 = pick_llm fall back 到 session.llm_id。零迁移成本 — 用户后期
按需在设置页填这两项就生效。
"""
from __future__ import annotations

from typing import Literal

import structlog

from infra.repo import crud

log = structlog.get_logger()


LLMPreference = Literal["cheap", "default", "pro"]


async def pick_llm(
    session: dict,
    preference: LLMPreference = "default",
) -> tuple[dict, str]:
    """Return (provider_row, model_name) for the requested preference.

    Fallback chain:
      cheap → app_settings.cheap_llm → session.llm_id → first provider+model
      pro   → app_settings.pro_llm   → session.llm_id → first provider+model
      default → session.llm_id                        → first provider+model
    """
    candidates: list[str] = []
    if preference == "cheap":
        configured = await _get_setting("cheap_llm")
        if configured:
            candidates.append(configured)
    elif preference == "pro":
        configured = await _get_setting("pro_llm")
        if configured:
            candidates.append(configured)

    # Always fall back to the session's bound LLM
    session_llm = (session.get("llm_id") or "").strip()
    if session_llm:
        candidates.append(session_llm)

    # And finally to the default_inception_model
    default_llm = await _get_setting("default_inception_model")
    if default_llm:
        candidates.append(default_llm)

    for cand in candidates:
        try:
            return await _resolve_llm_id(cand)
        except (ValueError, KeyError) as exc:
            log.warning("llm_picker.candidate_failed",
                        candidate=cand, error=str(exc))
            continue

    # Last resort: first provider+model in DB
    providers = await crud.get_all("llm_providers")
    if providers:
        first = providers[0]
        models = await crud.get_all(
            "llm_models", "provider_id = ?", (first["id"],),
        )
        if models:
            return first, models[0]["model_name"]

    raise ValueError(
        "no LLM available — configure at least one provider+model"
    )


async def _resolve_llm_id(llm_id: str) -> tuple[dict, str]:
    """Parse 'prov_xxx:model_name' (or 'prov_xxx' = first model) into the
    provider row + model name. Raises if not found."""
    if ":" in llm_id:
        provider_id, model_name = llm_id.split(":", 1)
    else:
        provider_id, model_name = llm_id, ""
    provider = await crud.get_by_id("llm_providers", provider_id)
    if not provider:
        raise KeyError(f"provider {provider_id} not found")
    if not model_name:
        models = await crud.get_all(
            "llm_models", "provider_id = ?", (provider_id,),
        )
        if not models:
            raise ValueError(f"no models bound to provider {provider_id}")
        model_name = models[0]["model_name"]
    return provider, model_name


async def _get_setting(key: str) -> str | None:
    rows = await crud.get_all("app_settings", "key = ?", (key,))
    if rows:
        val = str(rows[0].get("value") or "").strip()
        return val or None
    return None
