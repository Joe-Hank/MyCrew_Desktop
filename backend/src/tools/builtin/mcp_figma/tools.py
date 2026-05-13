"""Figma MCP tool bridges.

Targets the official Figma MCP server. We bridge the 5 most useful
tools for a UI/UX Designer / System Designer / Art Director agent:

  - figma_get_design_context  → designed-component code + screenshot + tokens
  - figma_get_screenshot      → just the rendered image
  - figma_get_metadata        → component tree / layer metadata
  - figma_get_variable_defs   → design tokens (colors / spacing / type)
  - figma_generate_diagram    → creates a FigJam diagram (good for system flow)

URL parsing reminder for the LLM (also in tool descriptions):
  figma.com/design/:fileKey/:fileName?node-id=:nodeId
  → fileKey is the path segment, nodeId is the query param.
  Convert any "-" in the node-id back to ":" when calling these tools.
"""
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedMCPTool


_SERVER = "figma"


class GetDesignContextArgs(BaseModel):
    fileKey: str = Field(..., description="Figma file key (from the URL path /design/<fileKey>/).")
    nodeId: str = Field(..., description="Node id (from the URL query node-id=). Use ':' not '-' between numbers.")


class FigmaGetDesignContext(GuardedMCPTool):
    name: str = "figma_get_design_context"
    description: str = (
        "Fetch a Figma node's full context: rendered code (React+Tailwind "
        "reference), screenshot, design tokens, and contextual hints. The "
        "primary tool for design-to-code work — call this first when "
        "implementing a Figma frame."
    )
    args_schema: type[BaseModel] = GetDesignContextArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "get_design_context"

    def _run(self, fileKey: str, nodeId: str) -> str:
        return self._guarded_call({"fileKey": fileKey, "nodeId": nodeId})


class GetScreenshotArgs(BaseModel):
    fileKey: str = Field(..., description="Figma file key.")
    nodeId: str = Field(..., description="Node id (':' format, not '-').")


class FigmaGetScreenshot(GuardedMCPTool):
    name: str = "figma_get_screenshot"
    description: str = "Fetch a PNG render of a Figma node for visual reference. Lightweight alternative to figma_get_design_context when you only need the image."
    args_schema: type[BaseModel] = GetScreenshotArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "get_screenshot"
    permission_kind: ClassVar[str | None] = "file_read"

    def _run(self, fileKey: str, nodeId: str) -> str:
        return self._guarded_call({"fileKey": fileKey, "nodeId": nodeId})


class GetMetadataArgs(BaseModel):
    fileKey: str = Field(..., description="Figma file key.")
    nodeId: str | None = Field(None, description="Optional node id to scope metadata; omit for whole file.")


class FigmaGetMetadata(GuardedMCPTool):
    name: str = "figma_get_metadata"
    description: str = "Fetch the layer tree / component metadata for a Figma file or node — names, types, nesting, but not the rendered pixels."
    args_schema: type[BaseModel] = GetMetadataArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "get_metadata"

    def _run(self, fileKey: str, nodeId: str | None = None) -> str:
        args: dict = {"fileKey": fileKey}
        if nodeId:
            args["nodeId"] = nodeId
        return self._guarded_call(args)


class GetVariableDefsArgs(BaseModel):
    fileKey: str = Field(..., description="Figma file key.")


class FigmaGetVariableDefs(GuardedMCPTool):
    name: str = "figma_get_variable_defs"
    description: str = "Fetch the design-token (variable) definitions of a Figma file — colors, spacing, type scales. Use these to align code-side tokens with the design source of truth."
    args_schema: type[BaseModel] = GetVariableDefsArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "get_variable_defs"

    def _run(self, fileKey: str) -> str:
        return self._guarded_call({"fileKey": fileKey})


class GenerateDiagramArgs(BaseModel):
    spec: str = Field(
        ...,
        description=(
            "Plain-text description of the diagram (e.g. 'sequence diagram "
            "of login flow: client → auth service → DB'). The Figma MCP "
            "lays this out in FigJam and returns the resulting file/node id."
        ),
    )


class FigmaGenerateDiagram(GuardedMCPTool):
    name: str = "figma_generate_diagram"
    description: str = (
        "Create a FigJam diagram from a text description (flowcharts, "
        "system maps, sequence diagrams). Returns the FigJam URL so "
        "humans can review. Useful for System Designer / Project Manager "
        "deliverables."
    )
    args_schema: type[BaseModel] = GenerateDiagramArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "generate_diagram"
    permission_kind: ClassVar[str | None] = "file_write"

    def _run(self, spec: str) -> str:
        return self._guarded_call({"spec": spec})


__all__ = [
    "FigmaGetDesignContext",
    "FigmaGetScreenshot",
    "FigmaGetMetadata",
    "FigmaGetVariableDefs",
    "FigmaGenerateDiagram",
]
