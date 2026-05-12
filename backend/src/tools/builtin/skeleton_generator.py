"""Generate BaseTool wrapper skeleton from MCP discovered_tools schema."""

from __future__ import annotations

import json
import re


def _schema_to_pydantic_type(schema: dict) -> str:
    t = schema.get("type", "str")
    mapping = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "list",
        "object": "dict",
    }
    return mapping.get(t, "str")


def _to_class_name(tool_name: str) -> str:
    parts = re.split(r"[_\-\s]+", tool_name)
    return "".join(p.capitalize() for p in parts)


def generate_wrapper_skeleton(
    mcp_server_id: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
) -> str:
    class_name = _to_class_name(tool_name)
    args_class = f"{class_name}Args"

    properties = input_schema.get("properties", {})
    required = set(input_schema.get("required", []))

    field_lines = []
    param_names = []
    for name, prop in properties.items():
        py_type = _schema_to_pydantic_type(prop)
        desc = prop.get("description", "")
        is_required = name in required

        if is_required:
            field_lines.append(
                f'    {name}: {py_type} = Field(..., description="{desc}")'
            )
        else:
            default = prop.get("default", "None")
            if isinstance(default, str) and default != "None":
                default = f'"{default}"'
            field_lines.append(
                f'    {name}: {py_type} | None = Field({default}, description="{desc}")'
            )
        param_names.append(name)

    if not field_lines:
        field_lines.append("    pass")

    fields_block = "\n".join(field_lines)
    params_str = ", ".join(f"{n}={n}" for n in param_names)
    run_params = ", ".join(f"{n}: ..." for n in param_names) if param_names else ""

    return f'''from typing import ClassVar

from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedMCPTool


class {args_class}(BaseModel):
{fields_block}


class {class_name}(GuardedMCPTool):
    name: str = "{tool_name}"
    description: str = "{tool_description}"
    args_schema: type[BaseModel] = {args_class}

    mcp_server_id: ClassVar[str] = "{mcp_server_id}"
    mcp_tool_name: ClassVar[str] = "{tool_name}"
    # Set permission_kind to file_read/file_write/cmd_exec/git/... for static
    # enforcement, or leave None to rely on name-based heuristics.
    permission_kind: ClassVar[str | None] = None

    def _run(self, {run_params}) -> str:
        return self._guarded_call({{{params_str}}})
'''
