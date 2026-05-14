"""Shared helpers for all 5 sub-agents.

Per design: sub-agents are STATELESS — they receive (user_message,
session) and produce a reply. They do NOT read message history; the
classifier already compressed relevant context into the intent +
session metadata.

Each sub-agent's `run(user_message, session)` returns a dict:
  {
    "reply_text": str,           # what to show user (always)
    "project_id": str | None,    # if a new project was created
    "blueprint": dict | None,    # if a blueprint was emitted
    "metadata": dict,            # extra info for events
  }
"""
from __future__ import annotations

from typing import Any, TypedDict


class SubAgentResult(TypedDict, total=False):
    reply_text: str
    project_id: str | None
    blueprint: dict | None
    metadata: dict[str, Any]


def empty_result(reply_text: str = "") -> SubAgentResult:
    return {
        "reply_text": reply_text,
        "project_id": None,
        "blueprint": None,
        "metadata": {},
    }


async def resolve_session_llm_with_provider(session: dict) -> tuple[dict, str]:
    """Resolve session.llm_id → (provider_row, model_name).

    Sub-agents that run CrewAI need the full provider row (for api_key,
    base_url, type). Raises ValueError if no LLM is configured.
    """
    from agents.compliance_gate import _resolve_session_llm
    from infra.repo import crud

    provider_id, model_name = await _resolve_session_llm(session)
    provider = await crud.get_by_id("llm_providers", provider_id)
    if not provider:
        raise ValueError(f"llm provider {provider_id} not found")
    return provider, model_name


async def run_crewai_agent(
    *,
    session_id: str,
    role: str,
    goal: str,
    backstory: str,
    description: str,
    expected_output: str,
    tools: list,
    provider: dict,
    model_name: str,
    max_iter: int,
) -> str:
    """Standardised CrewAI invocation. Wraps:
      - LLM construction via crewai_runner._build_crewai_llm
      - step_callback → WS broadcast (inception.probe / inception.delta)
      - asyncio.to_thread(crew.kickoff)

    Returns the final assistant text. Errors bubble up.
    """
    import asyncio
    from crewai import Agent, Crew, Process, Task
    from services.crewai_runner import _build_crewai_llm
    from api.ws import manager

    llm = _build_crewai_llm(provider, model_name)
    agent = Agent(
        role=role, goal=goal, backstory=backstory, llm=llm,
        tools=tools or None,
        max_iter=max_iter, verbose=False, allow_delegation=False,
    )
    task = Task(description=description, expected_output=expected_output, agent=agent)

    main_loop = asyncio.get_running_loop()
    step_n = {"n": 0}

    def _step_cb(step: object) -> None:
        step_n["n"] += 1
        text = _extract_step_text(step)
        try:
            asyncio.run_coroutine_threadsafe(
                manager.broadcast("inception.probe", {
                    "session_id": session_id,
                    "label": "step",
                    "n": step_n["n"],
                    "preview": (text or "")[:120],
                }),
                main_loop,
            )
            if text:
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast("inception.delta", {
                        "session_id": session_id, "text": text + "\n\n",
                    }),
                    main_loop,
                )
        except Exception:
            pass  # broadcast best-effort

    crew = Crew(
        agents=[agent], tasks=[task],
        process=Process.sequential, verbose=False, memory=False,
        step_callback=_step_cb,
    )
    result = await asyncio.to_thread(crew.kickoff)
    return str(getattr(result, "raw", result) or "").strip()


def _extract_step_text(step: object) -> str:
    """Best-effort text extraction from a CrewAI step (varies by version)."""
    try:
        output = getattr(step, "output", None)
        if isinstance(output, str) and output.strip():
            return output.strip()[:600]
        rv = getattr(step, "return_values", None)
        if isinstance(rv, dict) and rv.get("output"):
            return str(rv["output"])[:600]
        tool = getattr(step, "tool", None)
        tool_input = getattr(step, "tool_input", None)
        if tool:
            return f"⚙️ {tool}({str(tool_input)[:120]}...)" if tool_input else f"⚙️ {tool}"
        s = str(step)[:400]
        return s if s and s != "None" else ""
    except Exception:
        return ""
