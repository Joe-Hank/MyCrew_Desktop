"""One-shot importer: pull all configs from MyCrew_v2 into v3's SQLite DB.

Usage:
    cd backend
    python -m scripts.import_from_v2

Idempotent — re-run will skip records that already exist (matched by natural key).

Imports:
    - 6 LLM providers + 17 models (from data/config/llm_providers.yaml + .env)
    - 7 MCP servers (from .mcp.json)
    - 4 custom tools (Unity file ops)
    - 17 agents (from src/crewai_workflow/config/agents/*.yaml)
    - 8 crews (from src/crewai_workflow/crews/registry.py)
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import yaml

# Make sure we can import from backend root
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from infra.repo import crud  # noqa: E402
from infra.repo.sqlite_repo import init_db, close_db  # noqa: E402

V2_ROOT = Path(r"F:\ClaudeData\MyCrew_v2")


# ── Read v2 .env for API keys ──────────────────────────────────────

def _load_v2_env() -> dict[str, str]:
    """Parse v2's .env file. Returns {KEY: VALUE} dict."""
    env: dict[str, str] = {}
    env_path = V2_ROOT / ".env"
    if not env_path.exists():
        print(f"  ⚠  v2 .env not found at {env_path}")
        return env
    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            # Strip leading // (v2 uses these as section comments)
            if line.startswith("//") or line.startswith("#") or not line:
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# ── LLM provider config — only static metadata; keys filled at runtime ─

# Maps v2 provider id → (v3 name, v3 type, env var for key, base_url)
PROVIDER_META = {
    "claude": ("Claude", "anthropic", "ANTHROPIC_API_KEY", ""),
    # v2's "gpt" uses dashscope as backend (OpenAI compat); keep both
    "gpt": ("GPT", "openai", "OPENAI_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "qwen": ("Qwen", "qwen", "OPENAI_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "glm": ("GLM", "custom", "ZHIPUAI_API_KEY", "https://open.bigmodel.cn/api/paas/v4"),
    "deepseek": ("DeepSeek", "deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/v1"),
    "mimo": ("MiMo", "custom", "MIMO_API_KEY", ""),
}

# Thinking-capable model heuristics (v2 doesn't track this; we infer)
THINKING_MODELS = {
    "claude-sonnet-4-20250514",  # Anthropic extended thinking
    "o1", "o3-mini",  # OpenAI reasoning models
    "deepseek-v4-pro",  # DeepSeek reasoning variants (assumption)
}


# ── Helpers ────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


async def _find_first(table: str, where: str, params: tuple) -> dict | None:
    rows = await crud.get_all(table, where, params)
    return rows[0] if rows else None


# ── LLM Providers + Models ────────────────────────────────────────

# Build (v2-model-name → v3-llm-model-id) map for later use
MODEL_INDEX: dict[str, str] = {}
# Build (v2-provider-id → v3-provider-id) map
PROVIDER_INDEX: dict[str, str] = {}


async def import_llm_providers() -> None:
    env = _load_v2_env()
    cfg = _load_yaml(V2_ROOT / "data" / "config" / "llm_providers.yaml")
    providers = cfg.get("providers", [])

    for v2p in providers:
        v2_id = v2p["id"]
        meta = PROVIDER_META.get(v2_id)
        if not meta:
            print(f"  ⚠  Unknown provider {v2_id}, skipping")
            continue

        name, ptype, env_key, base_url = meta
        api_key = env.get(env_key, "")
        if not api_key:
            print(f"  ⚠  No env value for {env_key}; provider '{name}' will be inserted with empty key")

        existing = await _find_first("llm_providers", "name = ?", (name,))
        if existing:
            provider_id = existing["id"]
            print(f"  ↻ provider '{name}' exists ({provider_id})")
        else:
            row = await crud.insert("llm_providers", {
                "name": name,
                "type": ptype,
                "api_key_ref": api_key,
                "base_url": base_url,
            }, id_prefix="prov_")
            provider_id = row["id"]
            print(f"  + provider '{name}' → {provider_id}")

        PROVIDER_INDEX[v2_id] = provider_id

        # Import models
        for mname in v2p.get("models", []):
            existing_m = await _find_first(
                "llm_models", "provider_id = ? AND model_name = ?",
                (provider_id, mname),
            )
            if existing_m:
                MODEL_INDEX[mname] = existing_m["id"]
                print(f"      ↻ model '{mname}' exists")
                continue

            row = await crud.insert("llm_models", {
                "provider_id": provider_id,
                "model_name": mname,
                "label": mname,
                "max_tokens": None,
                "supports_thinking": 1 if mname in THINKING_MODELS else 0,
            }, id_prefix="model_")
            MODEL_INDEX[mname] = row["id"]
            print(f"      + model '{mname}'")


# ── MCP Servers ───────────────────────────────────────────────────

MCP_INDEX: dict[str, str] = {}  # v2 name → v3 mcp_server_id


async def import_mcp_servers() -> None:
    with open(V2_ROOT / ".mcp.json", "r", encoding="utf-8") as f:
        mcp_cfg = json.load(f)

    for name, srv in mcp_cfg.get("mcpServers", {}).items():
        existing = await _find_first("mcp_servers", "name = ?", (name,))
        if existing:
            MCP_INDEX[name] = existing["id"]
            print(f"  ↻ MCP '{name}' exists ({existing['id']})")
            continue

        # Determine transport: presence of 'command' = stdio, presence of 'url' = http
        command = srv.get("command")
        args = srv.get("args", [])
        env = srv.get("env", {})

        # All v2 MCPs are stdio (npx/uvx based commands); HTTP test_endpoint is just for health check
        transport = "stdio"

        row = await crud.insert("mcp_servers", {
            "name": name,
            "transport": transport,
            "command": command,
            "args": json.dumps(args),
            "url": None,
            "env_ref": json.dumps(env) if env else json.dumps({}),
            "enabled": 1,
            "auto_start": 1,
            "timeout": 30,
            "discovered_tools": json.dumps([]),
        }, id_prefix="mcp_")
        MCP_INDEX[name] = row["id"]
        print(f"  + MCP '{name}' → {row['id']}")


# ── Custom Tools ──────────────────────────────────────────────────

TOOL_INDEX: dict[str, str] = {}  # tool_name → v3 tool_id


CUSTOM_TOOLS = [
    {"name": "unity_read_file", "desc": "Read a Unity project file (read-only)"},
    {"name": "unity_write_file", "desc": "Write/create a Unity project file"},
    {"name": "unity_delete_file", "desc": "Delete a Unity project file"},
    {"name": "unity_list_files", "desc": "List files in a Unity project directory"},
]


async def import_tools() -> None:
    for t in CUSTOM_TOOLS:
        existing = await _find_first("tools", "name = ?", (t["name"],))
        if existing:
            TOOL_INDEX[t["name"]] = existing["id"]
            print(f"  ↻ tool '{t['name']}' exists")
            continue

        row = await crud.insert("tools", {
            "name": t["name"],
            "script_path": "src/tools/unity_file_tool.py",
            "source": "user",
            "checksum": None,
            "params_schema": json.dumps({}),
        }, id_prefix="tool_")
        TOOL_INDEX[t["name"]] = row["id"]
        print(f"  + tool '{t['name']}' → {row['id']}")


# ── Agents ────────────────────────────────────────────────────────

AGENT_INDEX: dict[str, str] = {}  # v2 agent key → v3 agent_id

# Preset → list of tool names
TOOL_PRESET_MAP = {
    "web": [],
    "read": ["unity_read_file", "unity_list_files"],
    "full_file": [
        "unity_read_file", "unity_write_file",
        "unity_delete_file", "unity_list_files",
    ],
}

# Heuristic: v2's `model` field → v3 provider:model llm_id
def _resolve_llm_id(model_name: str) -> str | None:
    """Build provider_id:model_name string for v3."""
    if model_name in MODEL_INDEX:
        # Find which provider it belongs to
        # MODEL_INDEX gives us the model row id; we need provider+model_name combo
        # In v3, llm_id format is "provider_id:model_name"
        for v2_pid, v3_pid in PROVIDER_INDEX.items():
            # Check if model belongs to this provider by re-querying
            return None  # filled below by direct lookup
    return None


def _normalize_goal(text: str | None) -> str | None:
    if not text:
        return None
    # Strip trailing newlines/spaces from YAML's preserved indentation
    return re.sub(r"\s+", " ", text.strip())


async def import_agents() -> None:
    agents_dir = V2_ROOT / "src" / "crewai_workflow" / "config" / "agents"
    yaml_files = sorted(agents_dir.glob("*.yaml"))

    # Build model_id → (provider_id, model_name) for llm_id construction
    all_models = await crud.get_all("llm_models")
    model_to_provider = {m["id"]: m["provider_id"] for m in all_models}
    provider_id_to_v2 = {v: k for k, v in PROVIDER_INDEX.items()}

    for yaml_path in yaml_files:
        cfg = _load_yaml(yaml_path)
        agent_key = cfg.get("name") or yaml_path.stem
        role = cfg.get("role", agent_key)

        existing = await _find_first("agents", "role = ?", (role,))
        if existing:
            AGENT_INDEX[agent_key] = existing["id"]
            print(f"  ↻ agent '{agent_key}' (role={role}) exists")
            continue

        # Resolve LLM
        model_name = cfg.get("model", "")
        llm_id: str | None = None
        if model_name and model_name in MODEL_INDEX:
            model_row_id = MODEL_INDEX[model_name]
            provider_v3_id = model_to_provider.get(model_row_id)
            if provider_v3_id:
                llm_id = f"{provider_v3_id}:{model_name}"

        # Resolve tools from preset
        preset = cfg.get("tools", {}).get("preset", "web")
        tool_names = TOOL_PRESET_MAP.get(preset, [])
        tool_ids = [TOOL_INDEX[n] for n in tool_names if n in TOOL_INDEX]

        # Memory path (from prompt.post_write[].path)
        memory_path = None
        post_write = (cfg.get("prompt") or {}).get("post_write") or []
        for pw in post_write:
            if pw.get("target") == "memory" and pw.get("path"):
                memory_path = pw["path"]
                break

        row = await crud.insert("agents", {
            "role": role,
            "goal": _normalize_goal(cfg.get("goal")),
            "backstory": _normalize_goal(cfg.get("backstory")),
            "reasoning": 1,
            "max_retry": cfg.get("max_iter", 3),
            "memory_enabled": 1 if memory_path else 0,
            "memory_path": memory_path,
            "thinking_mode": 0,
            "tool_ids": json.dumps(tool_ids),
            "llm_id": llm_id,
            "is_auto_generated": 0,
        }, id_prefix="agent_")
        AGENT_INDEX[agent_key] = row["id"]
        print(f"  + agent '{agent_key}' (role={role}) → {row['id']}"
              + (f" [llm={llm_id}]" if llm_id else "")
              + (f" [tools×{len(tool_ids)}]" if tool_ids else ""))


# ── Crews ─────────────────────────────────────────────────────────

# From v2 registry.py
CREW_DEFS = [
    ("planning", "sequential", ["project_manager"]),
    ("design", "sequential", ["system_designer", "level_designer", "narrative_designer"]),
    ("art", "sequential", [
        "art_director", "concept_artist", "modeler_3d",
        "animator", "vfx_artist", "ui_ux_designer",
    ]),
    ("tech", "sequential", ["technical_artist", "unity_developer"]),
    ("audio", "sequential", ["audio_designer"]),
    ("qa", "sequential", ["qa_engineer", "project_manager"]),
    ("qa_functional", "sequential", ["qa_engineer", "project_manager"]),
    ("debug_fix", "sequential", ["technical_artist", "unity_developer"]),
]


async def import_crews() -> None:
    for name, process, agent_keys in CREW_DEFS:
        existing = await _find_first("crews", "name = ?", (name,))
        if existing:
            print(f"  ↻ crew '{name}' exists")
            continue

        agent_ids = [AGENT_INDEX[k] for k in agent_keys if k in AGENT_INDEX]
        if len(agent_ids) != len(agent_keys):
            missing = [k for k in agent_keys if k not in AGENT_INDEX]
            print(f"  ⚠  crew '{name}': missing agents {missing}; using available {len(agent_ids)}")

        row = await crud.insert("crews", {
            "name": name,
            "process": process,
            "agent_ids": json.dumps(agent_ids),
            "is_auto_generated": 0,
        }, id_prefix="crew_")
        print(f"  + crew '{name}' [agents×{len(agent_ids)}] → {row['id']}")


# ── Main ──────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("MyCrew v2 → v3 config import")
    print("=" * 60)

    await init_db()

    print("\n[1/5] LLM providers + models ...")
    await import_llm_providers()

    print("\n[2/5] MCP servers ...")
    await import_mcp_servers()

    print("\n[3/5] Custom tools ...")
    await import_tools()

    print("\n[4/5] Agents ...")
    await import_agents()

    print("\n[5/5] Crews ...")
    await import_crews()

    # Summary
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  llm_providers : {await crud.count('llm_providers')}")
    print(f"  llm_models    : {await crud.count('llm_models')}")
    print(f"  mcp_servers   : {await crud.count('mcp_servers')}")
    print(f"  tools         : {await crud.count('tools')}")
    print(f"  agents        : {await crud.count('agents')}")
    print(f"  crews         : {await crud.count('crews')}")
    print("=" * 60)

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
