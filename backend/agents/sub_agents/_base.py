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

    Legacy helper. New code should use `resolve_llm(session, preference)`
    so the 3-tier picker (cheap/default/pro) takes effect.
    """
    from agents._llm_picker import pick_llm
    return await pick_llm(session, "default")


async def resolve_llm(
    session: dict,
    preference: str = "default",
) -> tuple[dict, str]:
    """Sub-agent entry point. Routes to `_llm_picker.pick_llm` with the
    sub-agent's DEFAULT_PARAMS['llm_preference']."""
    from agents._llm_picker import pick_llm
    return await pick_llm(session, preference)  # type: ignore[arg-type]


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
    temperature: float | None = None,
    max_tokens: int | None = None,
    broadcast_steps: bool = True,
) -> str:
    """Standardised CrewAI invocation. Wraps:
      - LLM construction via crewai_runner._build_crewai_llm
      - step_callback → WS broadcast (inception.probe / inception.delta)
      - asyncio.to_thread(crew.kickoff)

    `temperature` and `max_tokens` are passed to the LLM construction
    when set, letting per-intent sub-agents tune output style.

    `broadcast_steps=False` suppresses the inception.probe / inception.delta
    WS broadcasts — used by background repair kickoffs that shouldn't
    surface their internal steps in the user-facing chat stream.

    Returns the final assistant text. Errors bubble up.
    """
    import asyncio
    from crewai import Agent, Crew, Process, Task
    from services.crewai_runner import _build_crewai_llm
    from api.ws import manager

    llm = _build_crewai_llm(
        provider, model_name,
        temperature=temperature, max_tokens=max_tokens,
    )
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
        if not broadcast_steps:
            return
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
