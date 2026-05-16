"""Stage-C tests for the template-driven MCP config system."""
from __future__ import annotations

import pytest

from services.mcp_templates import (
    TEMPLATES,
    TemplateValidationError,
    assemble,
    detect_template,
    get_template,
    validate_field_values,
)


def test_every_template_has_required_fields():
    for t in TEMPLATES:
        assert t["id"] and t["name"] and t["description"]
        assert t["transport"] in ("stdio", "http")
        if t["transport"] == "stdio" and t["id"] != "custom":
            assert t.get("command"), f"{t['id']} stdio missing command"


def test_get_template_lookup():
    assert get_template("figma") is not None
    assert get_template("nonexistent") is None


def test_assemble_simple_no_fields():
    t = get_template("comfyui")
    out = assemble(t, {})
    assert out["transport"] == "stdio"
    assert out["command"] == "npx"
    assert out["args"] == ["-y", "comfyui-mcp"]
    assert out["env_ref"] == {}


def test_assemble_with_field_substitution():
    t = get_template("git")
    out = assemble(t, {"repository": "F:/MyProject"})
    assert "F:/MyProject" in out["args"]


def test_assemble_env_template_substitution():
    t = get_template("figma")
    out = assemble(t, {"api_key": "figd_real_token_here"})
    assert out["env_ref"]["FIGMA_API_KEY"] == "figd_real_token_here"


def test_assemble_notion_double_brace_literal():
    """Notion's env_template contains literal JSON braces ({{...}})
    which need to survive str.format unescaped."""
    t = get_template("notion")
    out = assemble(t, {"api_token": "secret_xxx"})
    val = out["env_ref"]["OPENAPI_MCP_HEADERS"]
    assert "Bearer secret_xxx" in val
    assert "{" in val and "}" in val  # JSON braces preserved


def test_assemble_http_template():
    t = get_template("unity_http")
    out = assemble(t, {"port": 8090})
    assert out["url"] == "http://127.0.0.1:8090/mcp"
    assert out["command"] is None


def test_validate_rejects_empty_required():
    t = get_template("figma")
    with pytest.raises(TemplateValidationError) as exc:
        validate_field_values(t, {})
    assert any(k == "api_key" for k, _ in exc.value.errors)


def test_validate_rejects_placeholder_value():
    t = get_template("figma")
    with pytest.raises(TemplateValidationError) as exc:
        validate_field_values(t, {"api_key": "${FIGMA_API_KEY}"})
    assert any("占位符" in m for _, m in exc.value.errors)


def test_validate_number_field():
    t = get_template("unity_http")
    with pytest.raises(TemplateValidationError):
        validate_field_values(t, {"port": "not-a-number"})
    # numeric string is accepted (int() converts it)
    validate_field_values(t, {"port": "8090"})


def test_custom_template_assembles_to_empty():
    t = get_template("custom")
    out = assemble(t, {})
    assert out == {}  # custom is special-cased upstream


def test_detect_template_npx_stdio():
    assert detect_template({
        "transport": "stdio",
        "command": "npx",
        "args": '["-y", "comfyui-mcp"]',
    }) == "comfyui"
    assert detect_template({
        "transport": "stdio",
        "command": "npx",
        "args": '["-y", "figma-developer-mcp", "--stdio"]',
    }) == "figma"


def test_detect_template_uvx_stdio():
    assert detect_template({
        "transport": "stdio",
        "command": "uvx",
        "args": '["blender-mcp"]',
    }) == "blender"


def test_detect_template_http():
    assert detect_template({
        "transport": "http",
        "url": "http://127.0.0.1:8090/mcp",
    }) == "unity_http"


def test_detect_template_unknown_returns_none():
    assert detect_template({
        "transport": "stdio",
        "command": "python",
        "args": '["/random/script.py"]',
    }) is None
