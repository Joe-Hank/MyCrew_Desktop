from __future__ import annotations

from pydantic import BaseModel, Field


class OkResponse(BaseModel):
    ok: bool = True
    data: dict | list | None = None


class ErrorResponse(BaseModel):
    ok: bool = False
    error: dict = Field(default_factory=lambda: {"code": "unknown", "message": ""})


# --- LLM ---

class LlmProviderCreate(BaseModel):
    name: str
    type: str
    api_key_ref: str | None = None
    base_url: str | None = None


class LlmProviderUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    api_key_ref: str | None = None
    base_url: str | None = None


class LlmModelCreate(BaseModel):
    provider_id: str
    model_name: str
    label: str | None = None
    max_tokens: int | None = None
    supports_thinking: bool = False


class LlmModelUpdate(BaseModel):
    model_name: str | None = None
    label: str | None = None
    max_tokens: int | None = None
    supports_thinking: bool | None = None


# --- MCP ---

class McpServerCreate(BaseModel):
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env_ref: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    auto_start: bool = True
    timeout: int = 30
    # Strategy C: when set, the backend assembles command/args/url/env_ref
    # from services/mcp_templates by substituting template_values into
    # the named template. Direct command/args/url/env_ref fields above
    # are ignored in that case (except for "custom", which falls back
    # to them).
    template_id: str | None = None
    template_values: dict = Field(default_factory=dict)


class McpServerUpdate(BaseModel):
    name: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    env_ref: dict[str, str] | None = None
    enabled: bool | None = None
    auto_start: bool | None = None
    timeout: int | None = None
    template_id: str | None = None
    template_values: dict | None = None


# --- Agent ---

class AgentCreate(BaseModel):
    role: str
    goal: str | None = None
    backstory: str | None = None
    reasoning: bool = False
    max_retry: int = 3
    memory_enabled: bool = False
    memory_path: str | None = None
    thinking_mode: bool = False
    tool_ids: list[str] = Field(default_factory=list)
    llm_id: str | None = None


class AgentUpdate(BaseModel):
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    reasoning: bool | None = None
    max_retry: int | None = None
    memory_enabled: bool | None = None
    memory_path: str | None = None
    thinking_mode: bool | None = None
    tool_ids: list[str] | None = None
    llm_id: str | None = None


# --- Crew ---

class CrewCreate(BaseModel):
    name: str
    process: str = "sequential"
    agent_ids: list[str] = Field(default_factory=list)


class CrewUpdate(BaseModel):
    name: str | None = None
    process: str | None = None
    agent_ids: list[str] | None = None


# --- Tool ---

class ToolCreate(BaseModel):
    name: str
    script_path: str | None = None
    source: str = "user"


# --- MCP Tool Call ---

class McpToolCall(BaseModel):
    server_id: str
    tool_name: str
    arguments: dict = Field(default_factory=dict)


# --- Config ---

class ConfigUpdate(BaseModel):
    key: str
    value: str


# --- Permission ---

class PermissionUpdate(BaseModel):
    id: str
    allowed: bool
