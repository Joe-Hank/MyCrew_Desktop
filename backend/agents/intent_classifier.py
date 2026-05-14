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


DEFAULT_PARAMS = {
    "llm_preference": "cheap",
    "temperature": 0.2,
    "max_tokens": 80,
}


_CLASSIFIER_SYSTEM_PROMPT = """你是 MyCrew 立项助手的意图路由器。给用户输入分类到 5 个 intent。

# 输出
严格 JSON（无 markdown 包装）：
{"intent": "<name>", "confidence": 0.0-1.0, "reason": "<≤20字>"}

# Intent 表

| name | 触发 | 典型话术 |
|---|---|---|
| create_new | 全新项目立项 | "做一个 X" / "Tetris 复刻" |
| iterate_existing | 在已有项目上加/改东西 | "加一关 boss" / "补存档" / session.mode=iterate |
| clarify_design | 问设计原因，不修改 | "为什么用 X" / "蓝图是啥样" |
| modify_blueprint | 改草稿任务（未启动） | "把任务 3 改详细些" / has_draft_blueprint=true |
| abort_or_restart | 中断/放弃 | "算了" / "重来" / "清空" |

# 决策规则
- has_draft_blueprint=true 且要修改 → modify_blueprint（不要误判成 create_new）
- mode=iterate → 优先 iterate_existing，除非显然是问问题
- 不确定 → create_new + 低 confidence

# 示例

输入: 做个吃豆人复刻
session: mode=create, template=unity_2d, has_project=false
→ {"intent": "create_new", "confidence": 0.95, "reason": "全新项目"}

输入: 把第 3 个任务的细节写详细些
session: mode=create, template=unity_2d, has_project=true, has_draft_blueprint=true
→ {"intent": "modify_blueprint", "confidence": 0.9, "reason": "改草稿任务"}

输入: 在 Mercy_1910 上加存档加密
session: mode=iterate, template=unity_2d, has_project=true
→ {"intent": "iterate_existing", "confidence": 0.95, "reason": "迭代加功能"}

输入: QA 那一步设计成那样的理由是什么？
session: has_project=true
→ {"intent": "clarify_design", "confidence": 0.85, "reason": "问设计原因"}

输入: 算了换个思路
→ {"intent": "abort_or_restart", "confidence": 0.95, "reason": "明确放弃"}"""


async def classify_intent(
    user_message: str,
    session: dict,
) -> IntentResult:
    """Run the classifier. Returns IntentResult; defaults to create_new on
    LLM/parse failure (fail-safe — create_new has the most graceful path).
    """
    from agents._llm_picker import pick_llm

    summary = _summarize_session(session)
    user_payload = (
        f"## session_summary\n{summary}\n\n"
        f"## user_message\n{user_message[:1500]}"
    )

    try:
        provider, model_name = await pick_llm(
            session, DEFAULT_PARAMS["llm_preference"],
        )
    except (ValueError, KeyError) as exc:
        log.warning("intent_classifier.no_llm", error=str(exc))
        return IntentResult(intent="create_new", confidence=0.0,
                            reason="no_llm_fallback")

    messages = [
        LlmMessage(role="system", content=_CLASSIFIER_SYSTEM_PROMPT),
        LlmMessage(role="user", content=user_payload),
    ]
    try:
        resp = await llm_gateway.chat(
            provider["id"], model_name, messages,
            max_tokens=DEFAULT_PARAMS["max_tokens"],
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
