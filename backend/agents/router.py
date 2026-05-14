"""Plan Maker 2.0 router — single dispatch entry point.

Pipeline (per user message):
  1. _enforce_choice_flow (caller's responsibility; we trust input is gated)
  2. pre_filter (regex + length + sensitive-word mask) → may DENY
  3. compliance_gate (LLM mini) → may CARE / HARMONIOUS_BLOCK / ALLOW
  4. intent_classifier (LLM mini) → 5 intents + confidence + reason
  5. sub_agents.<intent>.run(masked_text, session_context) → reply text

Returns a `RouterResult` describing what happened so `inception_svc` can
persist the assistant message + broadcast events. Never raises on
expected paths (DENY / CARE / blocked) — only on infra failures.

State persistence + event broadcast is OWNED by `inception_svc`; this
module is pure orchestration so it can be unit-tested without DB / WS.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

log = structlog.get_logger()


async def _trace_io(
    session_id: str,
    sub_agent: str,
    input_preview: str,
    output: Any,
    **extra: Any,
) -> None:
    """Emit a sub-agent IO trace — both to structlog (backend trace) AND
    to the frontend LogDrawer via WS. Best-effort: never throws."""
    payload = {
        "session_id": session_id,
        "sub_agent": sub_agent,
        "input_preview": (input_preview or "")[:200],
        "output_preview": (str(output) if not isinstance(output, str) else output)[:300],
        **extra,
    }
    log.info("router.sub_agent_io", **payload)
    try:
        from api.ws import manager
        await manager.broadcast("plan_maker.sub_agent_io", payload)
    except Exception:
        pass


RouterDecision = Literal[
    "pre_deny",
    "compliance_care",
    "compliance_blocked",
    "compliance_allow",   # internal; never final
    "dispatched",
    "router_error",
]


@dataclass
class RouterResult:
    decision: RouterDecision
    intent: str | None = None          # set when decision == "dispatched"
    reply_text: str = ""               # always set; what to show user
    metadata: dict[str, Any] = field(default_factory=dict)
    # Side-effect summary (sub-agent may have created project / tasks / etc).
    # `inception_svc` reads this to know whether to refetch & broadcast.
    project_id: str | None = None
    blueprint: dict | None = None


# ── Polite refusal / care templates (do NOT go into LLM prompts) ──

_CARE_REPLY = (
    "我注意到你提到了一些可能让你感到困扰的内容。\n\n"
    "**你的安全和健康是最重要的。** 如果你正在经历强烈的负面情绪、"
    "自伤倾向，或者面临法律风险，请：\n\n"
    "- 中国大陆心理援助热线：**400-161-9995**（24h）\n"
    "- 北京心理危机研究与干预中心：**010-82951332**\n"
    "- 全国法律援助热线：**12348**\n\n"
    "我是一个项目立项助手，没有专业资质处理情感/法律/医疗问题。"
    "但如果有具体的、安全合法的项目想做，我很乐意帮你拆解。\n\n"
    "如果只是开个玩笑，请直接换个话题，我们继续。"
)

_HARMONIOUS_BLOCK_REPLY = (
    "当前已开启**和谐模式**，无法生成涉及违法侵权 / 政治 / 色情 / 暴力的内容。\n\n"
    "如需放开限制，请在设置页将合规模式切换为「自由」。\n"
    "（默认是自由模式，可能某次被手动切换过。）"
)


async def dispatch(
    user_message: str,
    session: dict,
) -> RouterResult:
    """Entry point. Called from `inception_svc` per user message.

    `session` is the raw inception_sessions row dict — we read:
      session_id / mode / template_id / project_id / parent_project_id
    No message-history is read here; we treat each turn as stateless input
    (per design: classifier sees a 1-line summary, sub-agents see nothing).

    Returns RouterResult; the caller persists the assistant message and
    broadcasts events from the metadata.
    """
    from agents.pre_filter import run_pre_filter, PreFilterDeny

    # Log the round entry — pairs with stage-by-stage IO logs below so
    # operators can trace exactly how a user message moved through the
    # 5-stage pipeline (pre_filter → compliance → classifier → sub-agent).
    log.info("router.round_start",
             session_id=session.get("id"),
             mode=session.get("mode"),
             template_id=session.get("template_id"),
             project_id=session.get("project_id"),
             user_message_preview=user_message[:200])

    # Stage 0: pre-filter (rule-based, 0 LLM tokens)
    pre = run_pre_filter(user_message)
    if isinstance(pre, PreFilterDeny):
        log.info("router.pre_deny", reason=pre.reason,
                 session_id=session.get("id"))
        return RouterResult(
            decision="pre_deny",
            reply_text=pre.user_message,
            metadata={"reason": pre.reason},
        )

    masked = pre.masked_text

    # Stage 1: compliance gate (LLM mini)
    try:
        from agents.compliance_gate import check_compliance, ComplianceVerdict
    except ImportError:
        # Gate not yet wired (stage-A skeleton). Fall back to ALLOW.
        log.warning("router.compliance_gate_unavailable_default_allow")
        verdict = None
    else:
        verdict = await check_compliance(masked, session)
        await _trace_io(
            session.get("id") or "", "compliance_gate", masked,
            verdict.kind, reason=verdict.reason,
        )

    if verdict is not None:
        if verdict.kind == "CARE":
            log.info("router.compliance_care",
                     session_id=session.get("id"),
                     reason=verdict.reason)
            return RouterResult(
                decision="compliance_care",
                reply_text=_CARE_REPLY,
                metadata={"care_reason": verdict.reason},
            )
        if verdict.kind == "HARMONIOUS_BLOCK":
            # Check compliance_mode setting: only block in harmonious mode
            from agents.compliance_gate import is_harmonious_mode_on
            if await is_harmonious_mode_on():
                log.info("router.compliance_blocked",
                         session_id=session.get("id"),
                         reason=verdict.reason)
                return RouterResult(
                    decision="compliance_blocked",
                    reply_text=_HARMONIOUS_BLOCK_REPLY,
                    metadata={"block_reason": verdict.reason,
                              "mode": "harmonious"},
                )
            # else free mode → fall through to classifier as if ALLOW

    # Stage 2: intent classifier (LLM mini)
    try:
        from agents.intent_classifier import classify_intent
    except ImportError:
        log.warning("router.classifier_unavailable_default_create_new")
        # Skeleton fallback: assume create_new
        intent = "create_new"
        confidence = 0.0
        reason = "classifier_unavailable"
    else:
        cls_result = await classify_intent(masked, session)
        intent = cls_result.intent
        confidence = cls_result.confidence
        reason = cls_result.reason
        await _trace_io(
            session.get("id") or "", "intent_classifier", masked,
            intent, confidence=confidence, reason=reason,
        )

    log.info("router.intent_classified",
             session_id=session.get("id"), intent=intent,
             confidence=confidence)

    # Stage 3: dispatch to sub-agent
    sub_result = await _dispatch_to_sub_agent(intent, masked, session)
    await _trace_io(
        session.get("id") or "", intent, masked,
        sub_result.get("reply_text") or "",
        project_id=sub_result.get("project_id"),
    )
    return RouterResult(
        decision="dispatched",
        intent=intent,
        reply_text=sub_result.get("reply_text", ""),
        project_id=sub_result.get("project_id"),
        blueprint=sub_result.get("blueprint"),
        metadata={
            "intent": intent,
            "confidence": confidence,
            "classifier_reason": reason,
            **sub_result.get("metadata", {}),
        },
    )


async def _dispatch_to_sub_agent(
    intent: str, masked_text: str, session: dict,
) -> dict[str, Any]:
    """Route the (intent, masked_text, session) to the matching sub-agent.

    Returns a dict with at minimum {reply_text: str}; may also include
    {project_id, blueprint, metadata} for DB-mutating intents.

    During stage-A skeleton, all sub-agents return a placeholder. Later
    stages wire each one in turn.
    """
    # Lazy imports keep this module testable without sub-agents wired up
    try:
        if intent == "create_new":
            from agents.sub_agents.create_new import run as run_create
            return await run_create(masked_text, session)
        if intent == "iterate_existing":
            from agents.sub_agents.iterate_existing import run as run_iter
            return await run_iter(masked_text, session)
        if intent == "clarify_design":
            from agents.sub_agents.clarify_design import run as run_clarify
            return await run_clarify(masked_text, session)
        if intent == "modify_blueprint":
            from agents.sub_agents.modify_blueprint import run as run_modify
            return await run_modify(masked_text, session)
        if intent == "abort_or_restart":
            from agents.sub_agents.abort_or_restart import run as run_abort
            return await run_abort(masked_text, session)
    except ImportError as exc:
        log.warning("router.sub_agent_unavailable",
                    intent=intent, error=str(exc))
        return {
            "reply_text": (
                f"（{intent} 子 Agent 尚未接入；"
                "本轮请求未被处理，请稍后重试或换种说法）"
            ),
        }

    # Unknown intent — should never happen if classifier is well-trained
    log.warning("router.unknown_intent", intent=intent)
    return {"reply_text": f"（未知意图：{intent}）"}
