"""Stage 1: LLM-based compliance gate.

Tiny single-shot classifier. Three outcomes:

  ALLOW              — proceed to intent classifier
  CARE               — user appears to be in distress / asking about
                       self-harm / criminal intent etc. Router returns
                       a fixed care template without further LLM.
  HARMONIOUS_BLOCK   — request involves potentially illegal / political /
                       sexual / violent content. Router checks the
                       app-wide compliance_mode setting:
                         free       → treat as ALLOW (fall through)
                         harmonious → return polite refusal template

Prompt is ~80 tokens in / 10 out. Cheap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud

log = structlog.get_logger()


VerdictKind = Literal["ALLOW", "CARE", "HARMONIOUS_BLOCK"]


@dataclass
class ComplianceVerdict:
    kind: VerdictKind
    reason: str = ""    # short tag for logging / events


_GATE_SYSTEM_PROMPT = """你是 MyCrew 立项助手的合规门。判断用户消息属于哪一类，**只输出一个标签**：

ALLOW              — 正常的项目设计 / 修改 / 提问 / 闲聊式咨询（默认）
CARE               — 用户**自身**表达自杀、自残、犯罪意图，或强烈负面情绪求助
HARMONIOUS_BLOCK   — 请求生成涉嫌违法 / 政治敏感 / 色情 / 极端暴力 的内容

重要：
- 游戏里的暴力机制（"boss 战斗"、"死亡掉血"等）不算 HARMONIOUS_BLOCK
- 用户讨论游戏角色的"自杀"剧情不算 CARE
- 仅当用户**自己**表达负面状态时才用 CARE
- 不确定就给 ALLOW

只输出 ALLOW / CARE / HARMONIOUS_BLOCK 三个词之一，不要解释。"""


async def check_compliance(
    user_message: str,
    session: dict,
) -> ComplianceVerdict:
    """Run the gate. Returns ComplianceVerdict.

    Picks the LLM from session.llm_id, falling back to default_inception_model.
    """
    provider_id, model_name = await _resolve_session_llm(session)
    provider = await crud.get_by_id("llm_providers", provider_id)
    if not provider:
        log.warning("compliance_gate.no_provider_default_allow",
                    provider_id=provider_id)
        return ComplianceVerdict(kind="ALLOW", reason="no_provider")

    messages = [
        LlmMessage(role="system", content=_GATE_SYSTEM_PROMPT),
        LlmMessage(role="user", content=user_message[:2000]),  # cap input
    ]

    try:
        resp = await llm_gateway.chat(
            provider_id, model_name, messages,
            max_tokens=10,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("compliance_gate.llm_call_failed",
                    error=str(exc), provider_id=provider_id)
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
