"""Stage 2: 5-way intent classifier.

Output JSON: {"intent": <name>, "confidence": 0.0-1.0, "reason": <short>}

Intents (per plan 2026-05-15):

  create_new          — "做一个 2D 跳跃游戏" / "Tetris 复刻"
  iterate_existing    — "在 Mercy_1910 上加存档加密" / "补一关 boss"
  clarify_design      — "第 3 个任务为啥用 ScriptableObject" / "蓝图看看"
  modify_blueprint    — "把第 3 个任务的描述改详细" / "删掉那个 BGM 任务"
  abort_or_restart    — "算了不做了" / "换个思路重来" / "清空重新选"

Prompt ~200 in / 30 out. Decides each turn fresh (no stickiness).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

import structlog

from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud

log = structlog.get_logger()


IntentName = Literal[
    "create_new",
    "iterate_existing",
    "clarify_design",
    "modify_blueprint",
    "abort_or_restart",
]
_VALID_INTENTS: set[str] = {
    "create_new", "iterate_existing", "clarify_design",
    "modify_blueprint", "abort_or_restart",
}


@dataclass
class IntentResult:
    intent: IntentName
    confidence: float    # 0.0-1.0
    reason: str = ""     # short explanation


_CLASSIFIER_SYSTEM_PROMPT = """你是 MyCrew 立项助手的意图分类器。

输入：
- user_message: 用户当前输入
- session_summary: 当前会话状态摘要

输出**严格 JSON**（不要 markdown 代码块、不要任何解释）：
{"intent": "<name>", "confidence": 0.0-1.0, "reason": "<≤20字>"}

可选 intent（必须是以下 5 个之一）：

- create_new        用户想新建项目 / 设计一个游戏 / 提出全新需求
- iterate_existing  在已有项目（mode=iterate 或提到 root_path）上加东西、改东西
- clarify_design    问已有蓝图 / 任务的设计原因、解释、详情，**不修改**
- modify_blueprint  在草稿蓝图（has_draft_blueprint=true）上微调：加 task、删 task、改描述
- abort_or_restart  用户说"算了"、"重来"、"取消"、"清空"

规则：
- has_draft_blueprint=true 且用户想改 → modify_blueprint（不是 create_new）
- mode=iterate → 优先 iterate_existing（除非显然在问问题就 clarify_design）
- 不确定就给 create_new + 较低 confidence
- confidence 反映你的把握度，不是任务复杂度"""


async def classify_intent(
    user_message: str,
    session: dict,
) -> IntentResult:
    """Run the classifier. Returns IntentResult; defaults to create_new on
    LLM/parse failure (fail-safe — create_new has the most graceful path)."""
    from agents.compliance_gate import _resolve_session_llm

    summary = _summarize_session(session)
    user_payload = (
        f"## session_summary\n{summary}\n\n"
        f"## user_message\n{user_message[:1500]}"
    )

    try:
        provider_id, model_name = await _resolve_session_llm(session)
        provider = await crud.get_by_id("llm_providers", provider_id)
        if not provider:
            raise ValueError(f"provider {provider_id} not found")
    except Exception as exc:  # noqa: BLE001
        log.warning("intent_classifier.no_llm", error=str(exc))
        return IntentResult(intent="create_new", confidence=0.0,
                            reason="no_llm_fallback")

    messages = [
        LlmMessage(role="system", content=_CLASSIFIER_SYSTEM_PROMPT),
        LlmMessage(role="user", content=user_payload),
    ]
    try:
        resp = await llm_gateway.chat(
            provider_id, model_name, messages,
            max_tokens=80,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("intent_classifier.llm_call_failed", error=str(exc))
        return IntentResult(intent="create_new", confidence=0.0,
                            reason="llm_error")

    return _parse_intent_json(resp.text or "")


def _summarize_session(session: dict) -> str:
    """One-line structured session summary fed to the classifier in place
    of the full message history (per design: classifier sees no history)."""
    parts: list[str] = []
    mode = (session.get("mode") or "create").lower()
    parts.append(f"mode={mode}")
    parts.append(
        f"template_id={session.get('template_id') or 'none'}"
    )
    parts.append(
        f"has_project={'true' if session.get('project_id') else 'false'}"
    )
    # has_draft_blueprint is derived: there's a project_id AND we're still
    # in inception (no kick-off yet). For MVP, just check project_id —
    # caller can refine later.
    parts.append(
        f"has_draft_blueprint={'true' if session.get('project_id') else 'false'}"
    )
    return ", ".join(parts)


_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _parse_intent_json(text: str) -> IntentResult:
    """Pull the first JSON object out of the LLM output and validate it."""
    match = _JSON_RE.search(text)
    if not match:
        log.warning("intent_classifier.no_json", text=text[:200])
        return IntentResult(intent="create_new", confidence=0.0,
                            reason="no_json")

    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        log.warning("intent_classifier.bad_json",
                    error=str(exc), text=text[:200])
        return IntentResult(intent="create_new", confidence=0.0,
                            reason="bad_json")

    intent = str(obj.get("intent") or "").strip()
    if intent not in _VALID_INTENTS:
        log.warning("intent_classifier.unknown_intent", intent=intent)
        return IntentResult(intent="create_new", confidence=0.0,
                            reason=f"unknown_intent:{intent}")

    confidence_raw = obj.get("confidence", 0.5)
    try:
        confidence = max(0.0, min(1.0, float(confidence_raw)))
    except (TypeError, ValueError):
        confidence = 0.5
    reason = str(obj.get("reason") or "")[:60]

    return IntentResult(intent=intent, confidence=confidence, reason=reason)  # type: ignore[arg-type]
