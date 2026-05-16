"""MCP server configuration templates.

Strategy C from the 2026-05-16 server-config-hygiene discussion: every
common MCP server gets a typed schema that drives the create/edit
form, so users (or me, when adding new integrations) physically can't
save a config missing its required token / URL / path.

A template declares:
  - id              stable string used by frontend & DB lookup
  - name            display name
  - description     one-line summary shown in the picker
  - transport       'stdio' | 'http'
  - command         (stdio) the executable, e.g. 'npx'
  - args_template   (stdio) list of arg strings; values are substituted
                    via str.format with the user-provided field values
  - url_template    (http) URL pattern with the same substitution
  - env_template    dict mapping env-var name → value pattern (also
                    substituted). Keys without {placeholders} pass
                    through literally.
  - fields          list[FieldSpec] — each declares one user input
                    (label / type / required / placeholder)

`assemble(template, values)` turns a template + a user-supplied
{field_key: value} dict into the concrete {command, args, url, env_ref}
that goes into mcp_servers.

Add a new template by appending to TEMPLATES — that's the only required
edit; backend routes / frontend picker / save validation all read this
list dynamically.
"""
from __future__ import annotations

from typing import Any, Literal, TypedDict


class FieldSpec(TypedDict, total=False):
    key: str               # value lookup key (matches placeholders in templates)
    label: str             # display label
    type: Literal["text", "password", "number", "path", "url"]
    required: bool
    placeholder: str
    description: str       # one-line helper text under the field
    default: Any           # pre-fill value (omit / None → empty)


class Template(TypedDict, total=False):
    id: str
    name: str
    description: str
    transport: Literal["stdio", "http"]
    command: str | None        # stdio
    args_template: list[str]   # stdio (may contain {placeholders})
    url_template: str | None   # http (may contain {placeholders})
    env_template: dict[str, str]  # values may contain {placeholders}
    fields: list[FieldSpec]


# ── Template catalogue ────────────────────────────────────────────

TEMPLATES: list[Template] = [
    {
        "id": "comfyui",
        "name": "ComfyUI",
        "description": "本地 ComfyUI 图像生成（需要 ComfyUI 在 127.0.0.1:8188 运行）",
        "transport": "stdio",
        "command": "npx",
        "args_template": ["-y", "comfyui-mcp"],
        "env_template": {},
        "fields": [],
    },
    {
        "id": "blender",
        "name": "Blender",
        "description": "本地 Blender 3D 建模（需要 Blender 装好 Blender MCP 插件）",
        "transport": "stdio",
        "command": "uvx",
        "args_template": ["blender-mcp"],
        "env_template": {},
        "fields": [],
    },
    {
        "id": "git",
        "name": "Git",
        "description": "Git 仓库读写（status / log / diff / add / commit）",
        "transport": "stdio",
        "command": "uvx",
        "args_template": ["mcp-server-git", "--repository", "{repository}"],
        "env_template": {},
        "fields": [
            {
                "key": "repository",
                "label": "仓库路径",
                "type": "path",
                "required": True,
                "placeholder": r"F:\YourProject",
                "description": "本地 git 仓库根目录绝对路径",
            },
        ],
    },
    {
        "id": "unity_http",
        "name": "Unity (HTTP Bridge)",
        "description": "Unity Editor + Unity MCP Bridge（需要 Editor 开启并监听端口）",
        "transport": "http",
        "url_template": "http://127.0.0.1:{port}/mcp",
        "env_template": {},
        "fields": [
            {
                "key": "port",
                "label": "Bridge 端口",
                "type": "number",
                "required": True,
                "default": 8090,
                "description": "Unity MCP Bridge 监听端口（插件设置里看）",
            },
        ],
    },
    {
        "id": "figma",
        "name": "Figma",
        "description": "Figma 设计稿读取 (需要 Figma Personal Access Token)",
        "transport": "stdio",
        "command": "npx",
        "args_template": ["-y", "figma-developer-mcp", "--stdio"],
        "env_template": {"FIGMA_API_KEY": "{api_key}"},
        "fields": [
            {
                "key": "api_key",
                "label": "Figma API Token",
                "type": "password",
                "required": True,
                "placeholder": "figd_xxxxxxxxxxxxxxxx",
                "description": "Figma → Settings → Security → Personal access tokens 生成",
            },
        ],
    },
    {
        "id": "tavily",
        "name": "Tavily 搜索",
        "description": "Tavily 网络搜索 API（需要 API Key）",
        "transport": "stdio",
        "command": "npx",
        "args_template": ["-y", "tavily-mcp@latest"],
        "env_template": {"TAVILY_API_KEY": "{api_key}"},
        "fields": [
            {
                "key": "api_key",
                "label": "Tavily API Key",
                "type": "password",
                "required": True,
                "placeholder": "tvly-xxxxxxxx",
                "description": "https://tavily.com 注册后在 dashboard 获取",
            },
        ],
    },
    {
        "id": "notion",
        "name": "Notion",
        "description": "Notion 工作区读写（需要 Internal Integration Token）",
        "transport": "stdio",
        "command": "npx",
        "args_template": ["-y", "@notionhq/notion-mcp-server"],
        "env_template": {
            "OPENAPI_MCP_HEADERS": (
                '{{"Authorization": "Bearer {api_token}", '
                '"Notion-Version": "2022-06-28"}}'
            ),
        },
        "fields": [
            {
                "key": "api_token",
                "label": "Notion Integration Token",
                "type": "password",
                "required": True,
                "placeholder": "secret_xxxxxxxxxx",
                "description": "Notion → Settings → Integrations → 新建 Internal Integration",
            },
        ],
    },
    {
        # Free-form fallback — users with exotic MCP servers can still
        # build a config by hand. No fields = the frontend renders the
        # legacy "command/args/url" editor.
        "id": "custom",
        "name": "自定义",
        "description": "完全手动配置 command/args/url/env（适合非主流 MCP）",
        "transport": "stdio",
        "command": None,
        "args_template": [],
        "url_template": None,
        "env_template": {},
        "fields": [],  # custom is special-cased on the frontend
    },
]


def get_template(template_id: str) -> Template | None:
    """Look up a template by id; None if not found."""
    for t in TEMPLATES:
        if t["id"] == template_id:
            return t
    return None


# ── Field validation ──────────────────────────────────────────────


class TemplateValidationError(ValueError):
    """Raised when field values don't satisfy a template's schema.
    The `errors` list pairs each problem with the offending field key
    so the frontend can highlight inline."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__(
            "; ".join(f"{k}: {msg}" for k, msg in errors)
        )


_PLACEHOLDER_RE_HINT = "${"


def validate_field_values(
    template: Template, values: dict[str, Any],
) -> None:
    """Raise TemplateValidationError if any required field is missing,
    empty, or contains a literal ${...} placeholder (the same shape that
    used to land in env_ref and hang the connect)."""
    errors: list[tuple[str, str]] = []
    for field in template.get("fields", []):
        key = field["key"]
        required = field.get("required", False)
        raw = values.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if required:
                errors.append((key, "必填字段不能为空"))
            continue
        # Reject literal ${...} placeholders — common when copy-pasting
        # an example config.
        if isinstance(raw, str) and _PLACEHOLDER_RE_HINT in raw:
            errors.append((
                key,
                "看起来是 ${...} 占位符，请填真实值（如 token / 路径 / 端口）",
            ))
        # Type-specific basics — keep them light, just enough to catch
        # the common "I typed something weird" errors.
        if field.get("type") == "number":
            try:
                int(raw)
            except (TypeError, ValueError):
                errors.append((key, "需要是整数"))
        if field.get("type") == "url" and isinstance(raw, str):
            if not (raw.startswith("http://") or raw.startswith("https://")):
                errors.append((key, "需要以 http:// 或 https:// 开头"))
    if errors:
        raise TemplateValidationError(errors)


# ── Assembly ──────────────────────────────────────────────────────


def assemble(
    template: Template, values: dict[str, Any],
) -> dict[str, Any]:
    """Substitute user values into the template, returning a dict
    suitable for mcp_servers row creation: {transport, command, args,
    url, env_ref}. Raises TemplateValidationError on any missing /
    placeholder / type-mismatched field.

    `custom` is special — it returns an empty skeleton; the frontend
    sends raw command/args/url/env_ref directly in that path.
    """
    if template["id"] == "custom":
        return {}

    validate_field_values(template, values)

    def _sub(s: str) -> str:
        try:
            return s.format(**values)
        except (KeyError, IndexError) as exc:
            raise TemplateValidationError([
                ("", f"模板里引用了未提供的字段：{exc}"),
            ]) from exc

    out: dict[str, Any] = {"transport": template["transport"]}
    if template["transport"] == "stdio":
        out["command"] = template.get("command")
        out["args"] = [_sub(a) for a in template.get("args_template", [])]
        out["url"] = None
    else:
        out["url"] = _sub(template.get("url_template") or "")
        out["command"] = None
        out["args"] = []
    env_template = template.get("env_template", {})
    out["env_ref"] = {k: _sub(v) for k, v in env_template.items()}
    return out


# ── Reverse map: existing server → template ──────────────────────


def detect_template(server_row: dict[str, Any]) -> str | None:
    """Guess which template a hand-written or legacy server row was
    built from, by matching command + args[0..1] fingerprints. Returns
    None when the row doesn't match any template — those become
    "custom" after the one-time backfill.
    """
    import json

    transport = server_row.get("transport")
    command = server_row.get("command")
    args_raw = server_row.get("args") or "[]"
    if isinstance(args_raw, str):
        try:
            args = json.loads(args_raw)
        except (json.JSONDecodeError, TypeError):
            args = []
    else:
        args = args_raw or []

    # http transport → only unity_http exists right now
    if transport == "http":
        url = server_row.get("url") or ""
        if "/mcp" in url and "127.0.0.1" in url:
            return "unity_http"
        return None

    # stdio: match by (command, first arg(s))
    if command == "npx" and len(args) >= 2:
        if args[0] == "-y":
            pkg = args[1]
            if pkg == "comfyui-mcp":
                return "comfyui"
            if pkg == "figma-developer-mcp":
                return "figma"
            if pkg.startswith("tavily-mcp"):
                return "tavily"
            if pkg == "@notionhq/notion-mcp-server":
                return "notion"
    if command == "uvx" and len(args) >= 1:
        if args[0] == "blender-mcp":
            return "blender"
        if args[0] == "mcp-server-git":
            return "git"
    return None
