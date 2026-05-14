"""Plan Maker 2.0 — Dify-style intent router + 5 sub-agents.

Replaces the old monolithic Plan Maker (one 1800-token backstory + 5 LLM
iterations all in one) with a thin dispatch layer:

  USER MESSAGE
    → pre_filter (regex + length + sensitive-word mask)
    → compliance_gate (LLM mini, ALLOW / CARE / HARMONIOUS_BLOCK)
    → intent_classifier (LLM mini, 5 intents)
    → sub_agents.<intent>.run(user_message, session_context)

Token savings vs the old monolithic Plan Maker: 70-99% per round
depending on the path. See `docs/_tmp_PLAN_MAKER_PROMPTS_AUDIT.md` and
`C:/Users/26636/.claude/plans/generic-greeting-steele.md`.

Public entry point: `agents.router.dispatch(...)` — replaces
`inception_svc._run_plan_maker`.
"""
