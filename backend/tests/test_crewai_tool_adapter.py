"""Regression test for _adapt_to_base_tool (2026-05-16 incident).

CrewAI 1.14's Agent rejects tools that aren't BaseTool instances. Our
Unity MCP tools are CrewStructuredTool; without the adapter every
agent with a Unity tool crashes at instantiation with
"5 validation errors for Agent: tools.0 ... CrewStructuredTool".

This test ensures:
  - Real CrewStructuredTool instances become BaseTool after wrapping
  - Real BaseTool instances pass through unchanged
  - Adapter preserves name / description / args_schema metadata
"""
from __future__ import annotations

import pytest

from services.crewai_runner import _adapt_to_base_tool


def test_unity_tool_becomes_base_tool():
    from crewai.tools import BaseTool
    from crewai.tools.structured_tool import CrewStructuredTool
    from src.tools.builtin.unity import manage_asset_tool

    assert isinstance(manage_asset_tool, CrewStructuredTool)
    assert not isinstance(manage_asset_tool, BaseTool)

    wrapped = _adapt_to_base_tool(manage_asset_tool)
    assert isinstance(wrapped, BaseTool)
    assert wrapped.name == manage_asset_tool.name
    # CrewStructuredTool's description prefixes "Tool Name:..."; we forward
    # whatever it set. Just assert it's non-empty + a string.
    assert isinstance(wrapped.description, str) and wrapped.description
    assert wrapped.args_schema is manage_asset_tool.args_schema


def test_base_tool_passes_through_unchanged():
    from crewai.tools import BaseTool

    class _Already(BaseTool):
        name: str = "already_base"
        description: str = "x"

        def _run(self) -> str:
            return "ok"

    inst = _Already()
    assert _adapt_to_base_tool(inst) is inst


def test_unknown_shape_returns_unchanged():
    """Defensive — wrapping a plain object (no name/description) shouldn't
    crash; just hand it back so caller can deal."""
    obj = object()
    assert _adapt_to_base_tool(obj) is obj


def test_unity_tools_can_be_attached_to_agent():
    """End-to-end of the actual bug: Agent(tools=[unity_tool]) raised
    `5 validation errors for Agent` before the adapter."""
    from pydantic import ValidationError
    from crewai import Agent
    from src.tools.builtin.unity import (
        manage_asset_tool, manage_material_tool, manage_texture_tool,
    )

    raw = [manage_asset_tool, manage_material_tool, manage_texture_tool]

    # Without the adapter the tools field fails Pydantic validation.
    with pytest.raises(ValidationError, match="instance of BaseTool"):
        # Use 'gpt-4' as a dummy native model — Agent will try to build
        # an LLM and may fail later for unrelated reasons, but tools
        # validation runs FIRST so we'd see the ValidationError.
        Agent(role="x", goal="y", backstory="z", llm="gpt-4", tools=raw)

    # With the adapter, tools validation passes. LLM init may still
    # fail for missing API key — catch that separately so the test
    # doesn't depend on env vars.
    wrapped = [_adapt_to_base_tool(t) for t in raw]
    try:
        Agent(role="x", goal="y", backstory="z", llm="gpt-4", tools=wrapped)
    except ValidationError as exc:
        # Only acceptable validation failure: NOT about tools field.
        msg = str(exc)
        assert "tools" not in msg.split("\n")[1].lower(), (
            f"adapter didn't satisfy tools validation: {msg[:300]}"
        )
    except Exception:
        # LLM init or other downstream — not our concern.
        pass
