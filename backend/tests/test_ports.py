"""Tests for Port protocol interfaces — verify they can be imported and typed correctly."""
import pytest


def test_all_ports_importable():
    """All port protocols should be importable from the ports package."""
    from ports import (
        EventBusPort,
        InteractionPort,
        PromptCtx,
        Choice,
        LlmPort,
        LlmMessage,
        LlmUsage,
        LlmResponse,
        MCPPort,
        RepoPort,
    )
    # All should be accessible
    assert EventBusPort is not None
    assert InteractionPort is not None
    assert LlmPort is not None
    assert MCPPort is not None
    assert RepoPort is not None


def test_llm_port_dataclasses():
    """LLM port data classes should be instantiable."""
    from ports.llm_port import LlmMessage, LlmUsage, LlmResponse

    msg = LlmMessage(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"

    usage = LlmUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    assert usage.total_tokens == 30

    resp = LlmResponse(text="Hi", usage=usage, model="gpt-4o")
    assert resp.text == "Hi"
    assert resp.thinking is None


def test_interaction_port_dataclasses():
    """InteractionPort supporting data classes should work."""
    from ports.interaction_port import PromptCtx, Choice

    ctx = PromptCtx(project_id="p1", task_id="t1", request_id="r1", title="Test")
    assert ctx.project_id == "p1"

    choice = Choice(value="yes", label="Yes, proceed")
    assert choice.value == "yes"


def test_event_bus_port_protocol():
    """EventBusPort should define subscribe and publish."""
    from ports.event_bus_port import EventBusPort
    import inspect
    # Protocol should have the expected methods
    hints = {name for name, _ in inspect.getmembers(EventBusPort)
             if not name.startswith("_")}
    assert "subscribe" in hints
    assert "publish" in hints


def test_mcp_port_protocol():
    """MCPPort should define connect/disconnect/call_tool/list_tools."""
    from ports.mcp_port import MCPPort
    import inspect
    hints = {name for name, _ in inspect.getmembers(MCPPort)
             if not name.startswith("_")}
    assert "connect" in hints
    assert "disconnect" in hints
    assert "call_tool" in hints
    assert "list_tools" in hints


def test_repo_port_protocol():
    """RepoPort should define CRUD operations."""
    from ports.repo_port import RepoPort
    import inspect
    hints = {name for name, _ in inspect.getmembers(RepoPort)
             if not name.startswith("_")}
    assert "insert" in hints
    assert "get_by_id" in hints
    assert "get_all" in hints
    assert "update_by_id" in hints
    assert "delete_by_id" in hints
    assert "count" in hints
    assert "paginate" in hints
