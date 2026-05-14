"""Stage 1: LLM-based compliance gate.

Three-way classifier with few-shot examples covering the tricky boundaries
(game-mechanics violence vs real violence; software help-seeking vs care
trigger; mixed cases where care-priority dominates).

Outcomes:
  ALLOW              — proceed to intent classifier
  CARE               — user shows distress about themselves; router
                       returns a fixed care template, no further LLM
  HARMONIOUS_BLOCK   — content-generation request that the harmonious
                       compliance mode would block (free mode falls
                       through to ALLOW automatically in router.py)

Uses the cheapest LLM (`llm_preference="cheap"`), temperature=0,
max_tokens=10. Care-priority is enforced both in the prompt and in the
label parser.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway

log = structlog.get_logger()


VerdictKind = Literal["ALLOW", "CARE", "HARMONIOUS_BLOCK"]


# Per-intent LLM/sampling params (per Plan Maker 2.0 design)
DEFAULT_PARAMS = {
    "llm_preference": "cheap",
    "temperature": 0,
    "max_tokens": 10,
}


@dataclass
class ComplianceVerdict:
    kind: VerdictKind
    reason: str = ""    # short tag for logging / events


_GATE_SYSTEM_PROMPT = """你是 MyCrew 立项助手的合规门。判断用户消息属于哪一类：

ALLOW    — 项目设计 / 修改 / 提问 / 软件咨询
CARE     — 用户**自身**自杀、自残、犯罪、强烈负面情绪求助
HARMONIOUS_BLOCK — 请求生成违法 / 政治 / 色情 / 极端暴力 的实际内容

**只输出标签**（不解释、不换行）。CARE 优先级最高。

# 示例

用户: 做一个 Tetris 复刻
→ ALLOW

用户: 我想跳楼了不想活了
→ CARE

用户: 画一幅 NSFW 的图
→ HARMONIOUS_BLOCK

用户: 设计一个 boss 战，玩家死了就 game over
→ ALLOW （游戏机制描述，不是真实暴力）

用户: 怎么用 MyCrew 暂停项目？
→ ALLOW （软件使用咨询）

用户: 我撑不下去了。能帮我设计一个游戏吗？
→ CARE （混合情况，care 优先）"""


async def check_compliance(
    user_message: str,
    session: dict,
) -> ComplianceVerdict:
    """Run the gate. Returns ComplianceVerdict.

    Resolves the LLM via the 3-tier picker — prefers app_settings.cheap_llm
    (per DEFAULT_PARAMS); falls back to session.llm_id / first provider.
    """
    from agents._llm_picker import pick_llm

    try:
        provider, model_name = await pick_llm(
            session, DEFAULT_PARAMS["llm_preference"],
        )
    except (ValueError, KeyError) as exc:
        log.warning("compliance_gate.no_llm_default_allow", error=str(exc))
        return ComplianceVerdict(kind="ALLOW", reason="no_llm")

    messages = [
        LlmMessage(role="system", content=_GATE_SYSTEM_PROMPT),
        LlmMessage(role="user", content=user_message[:2000]),  # cap input
    ]

    try:
        resp = await llm_gateway.chat(
            provider["id"], model_name, messages,
            max_tokens=DEFAULT_PARAMS["max_tokens"],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("compliance_gate.llm_call_failed",
                    error=str(exc), provider_id=provider["id"])
        # Fail open — let the user through rather than blocking on infra error
        return ComplianceVerdict(kind="ALLOW", reason="llm_error")

    label = _parse_label(resp.text)
    return ComplianceVerdict(kind=label, reason="llm_decision")


def _parse_label(raw: str) -> VerdictKind:
    """Extract one of the three labels from LLM output. Defaults to ALLOW
    on ambiguity (fail-open)."""
    text = (raw or "").strip().upper()
    if "CARE" in text:
        return "CARE"
    if "HARMONIOUS" in text or "BLOCK" in text:
        return "HARMONIOUS_BLOCK"
    return "ALLOW"


async def is_harmonious_mode_on() -> bool:
    """Read the app-wide compliance_mode setting."""
    from services.settings_svc import get_compliance_mode
    return (await get_compliance_mode()) == "harmonious"


# ── LLM resolution (mirrors inception_svc._resolve_llm but standalone) ─

async def _resolve_session_llm(session: dict) -> tuple[str, str]:
    """Returns (provider_id, model_name) from the session's llm_id, with
    fallback to app_settings.default_inception_model and finally the
    first provider+model in DB."""
    llm_id = (session.get("llm_id") or "").strip()

    if not llm_id:
        # default_inception_model from app_settings
        rows = await crud.get_all(
            "app_settings", "key = ?", ("default_inception_model",),
        )
        if rows:
            llm_id = str(rows[0].get("value") or "")

    if llm_id and ":" in llm_id:
        provider_id, model_name = llm_id.split(":", 1)
        return provider_id, model_name

    if llm_id:
        # provider_id only — pick its first model
        models = await crud.get_all(
            "llm_models", "provider_id = ?", (llm_id,),
        )
        if models:
            return llm_id, models[0]["model_name"]

    # Last resort: first provider's first model
    providers = await crud.get_all("llm_providers")
    if providers:
        first = providers[0]
        models = await crud.get_all(
            "llm_models", "provider_id = ?", (first["id"],),
        )
        if models:
            return first["id"], models[0]["model_name"]

    raise ValueError("no LLM provider configured")
