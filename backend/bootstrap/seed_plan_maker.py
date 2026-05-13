"""Idempotent Plan Maker agent prompt seeding.

Plan Maker is the special CrewAI agent that turns a user's project idea
into a concrete workflow (Project + Tasks). It needs a clear, MCP-aware
prompt and access to the `create_workflow` tool.

This module:
  1. Ensures a row exists in `agents` with role='Plan Maker'.
  2. Computes a hash of the current prompt template + sets it on the
     row only if the hash differs from `app_settings.plan_maker_prompt_version`.
     This makes the seeder safe to run on every startup without
     clobbering rows that are already up-to-date.
  3. Ensures the row's `tool_ids` JSON array contains the
     `create_workflow` tool id.
"""
from __future__ import annotations

import hashlib
import json

import structlog

from infra.repo import crud

log = structlog.get_logger()


PLAN_MAKER_GOAL = (
    "MyCrew Plan Maker：把用户的**项目设计需求**拆成可执行任务流并持久化。"
    "非项目设计的话题（闲聊/百科/政治等）礼貌拒绝并请用户回到立项主题。"
)

PLAN_MAKER_BACKSTORY_TEMPLATE = """## 可用 MCP
{available_mcp_servers}

## 可用 Agent
{available_agents}

## 编排规则
- 任务数 1-2 → sequential；3-5 → crew；6+ → flow
- 末尾必须有 kind="final_qa" 任务，deps 指向所有终端节点
- 每个任务的 output_schema 是合法 JSON Schema；`{}` 表示自由文本
- 需要 MCP（blender/unity/comfyui 等）的任务，在 detail 里点名

## 技术栈默认（重要）
- 游戏/交互/3D/VR/AR 项目默认 **Unity 2022 LTS + C# + Prefab + UGUI/UI Toolkit
  + Input System + Animator + URP**。禁止默认 HTML/JS/Canvas/Phaser/Three.js/
  Pygame 等 Web 或 Python 游戏栈，除非用户明确指定。
- 美术建模走 Blender MCP，图像生成走 ComfyUI MCP。
- 工具/脚本/数据类按需选合适栈。

## 何时直接产出 vs 何时澄清
- **默认直接产出**。著名原型（俄罗斯方块/吃豆人/Tetris/Pac-Man/Snake/Mario/
  待办/计算器 等）按合理默认假设立刻调工具，**别问澄清问题**。
- 只有输入极度抽象（"做个项目"/"帮我做个东西"）才提一个澄清问题。

## 范围限制
非项目设计请求 → 不调工具，回复："（不在项目立项范围）— 我只能帮你拆解项目任务。
请描述具体项目，例如：「做一个 Unity 平台跳跃游戏，三关，每关有 boss」。"

## 工具调用协议（严格）
方案明确时**必须依次调两个工具**：
1. `create_workflow(name, execution_kind, tasks)` — 持久化项目 + 任务列表
2. `assign_agents(assignments)` — 给每个 task 指定 agent：
   - `existing_agent_id`：复用上面列表里合适的 agent
   - `new_agent: {role, goal, backstory}`：现有不匹配时**新建**（自动出现在团队页）。
     role 简洁专业，如 "Unity 客户端工程师"、"ComfyUI 图像设计师"、"Blender 资产建模师"。

工具调用后**立刻用一句中文确认作为最终回复**（例："任务方案已生成。已指派 N
个 Agent，新建 M 个：X, Y"），不要再列任务、不要重复、不要思考下一步。
不要在文本里输出 ```json 代码块。"""


def _prompt_version_hash() -> str:
    """Hash of the *template* — doesn't change when MCPs/agents are added/removed."""
    h = hashlib.sha256()
    h.update(PLAN_MAKER_GOAL.encode("utf-8"))
    h.update(PLAN_MAKER_BACKSTORY_TEMPLATE.encode("utf-8"))
    return h.hexdigest()[:16]


async def ensure_plan_maker_agent(tool_name_to_id: dict[str, str]) -> str | None:
    """Ensure Plan Maker agent exists with current prompt + create_workflow tool.

    Returns the agent id, or None if seeding failed.
    """
    rows = await crud.get_all("agents", "role = ?", ("Plan Maker",))

    create_workflow_id = tool_name_to_id.get("create_workflow")
    if not create_workflow_id:
        log.warning("seed.plan_maker.no_create_workflow_tool")

    # Compose the desired tool_ids set (just create_workflow for now)
    desired_tool_ids = [create_workflow_id] if create_workflow_id else []

    current_version = _prompt_version_hash()
    stored_version_rows = await crud.get_all(
        "app_settings", "key = ?", ("plan_maker_prompt_version",)
    )
    stored_version = stored_version_rows[0]["value"] if stored_version_rows else ""

    if not rows:
        # Create a new Plan Maker agent
        row = await crud.insert("agents", {
            "role": "Plan Maker",
            "goal": PLAN_MAKER_GOAL,
            "backstory": PLAN_MAKER_BACKSTORY_TEMPLATE,
            "reasoning": 1,
            "max_retry": 5,
            "memory_enabled": 0,
            "memory_path": None,
            "thinking_mode": 0,
            "tool_ids": json.dumps(desired_tool_ids),
            "llm_id": None,
            "is_auto_generated": 1,
        }, id_prefix="agent_")
        log.info("seed.plan_maker.created", id=row["id"])
        await _set_app_setting("plan_maker_prompt_version", current_version)
        return row["id"]

    row = rows[0]
    agent_id = row["id"]

    # Decode existing tool_ids
    existing_tool_ids = row.get("tool_ids", "[]")
    if isinstance(existing_tool_ids, str):
        try:
            existing_tool_ids = json.loads(existing_tool_ids)
        except (json.JSONDecodeError, TypeError):
            existing_tool_ids = []

    needs_update = False
    updates: dict = {}

    if stored_version != current_version:
        updates["goal"] = PLAN_MAKER_GOAL
        updates["backstory"] = PLAN_MAKER_BACKSTORY_TEMPLATE
        needs_update = True

    # Plan Maker must be able to call BOTH create_workflow and assign_agents
    # in one round. CrewAI's max_iter caps total LLM iterations and each
    # tool call consumes one — anything below 3 cripples the two-tool flow.
    # Floor at 5 so any pre-existing row with max_retry=1 (an older default)
    # gets healed on next startup.
    current_max_retry = int(row.get("max_retry") or 0)
    if current_max_retry < 5:
        updates["max_retry"] = 5
        needs_update = True

    # Always ensure create_workflow is in tool_ids (idempotent)
    if create_workflow_id and create_workflow_id not in existing_tool_ids:
        merged = list(existing_tool_ids) + [create_workflow_id]
        updates["tool_ids"] = json.dumps(merged)
        needs_update = True

    if needs_update:
        await crud.update_by_id("agents", agent_id, updates)
        log.info("seed.plan_maker.updated", id=agent_id,
                 prompt_changed=("goal" in updates),
                 tool_added=("tool_ids" in updates))
        if "goal" in updates:
            await _set_app_setting("plan_maker_prompt_version", current_version)

    return agent_id


async def _set_app_setting(key: str, value: str) -> None:
    """Upsert into app_settings table."""
    rows = await crud.get_all("app_settings", "key = ?", (key,))
    if rows:
        from infra.repo.sqlite_repo import get_db
        db = await get_db()
        await db.execute("UPDATE app_settings SET value = ? WHERE key = ?",
                         (value, key))
        await db.commit()
    else:
        from infra.repo.sqlite_repo import get_db
        db = await get_db()
        await db.execute("INSERT INTO app_settings (key, value) VALUES (?, ?)",
                         (key, value))
        await db.commit()


# ── runtime placeholder rendering ─────────────────────────────────

async def render_plan_maker_backstory(template: str) -> str:
    """Replace {available_mcp_servers} and {available_agents} placeholders
    with live DB content. Compact one-line-per-entry format keeps the
    backstory short — every token here is paid for on every LLM round.

    Agent entries include the `id` field so Plan Maker can reference them
    directly via `assign_agents.existing_agent_id`; without the id it
    would have to invent one from the role name."""
    mcp_rows = await crud.get_all("mcp_servers")
    enabled_mcps = [r for r in mcp_rows if r.get("enabled", 1)]
    mcp_lines = [
        f"- {s.get('name','')}" for s in enabled_mcps if s.get("name")
    ]
    mcp_block = "\n".join(mcp_lines) if mcp_lines else "（无）"

    agent_rows = await crud.get_all("agents")
    other_agents = [a for a in agent_rows if a.get("role") != "Plan Maker"]
    agent_lines = []
    for a in other_agents:
        aid = a.get("id", "")
        role = a.get("role", "")
        goal = (a.get("goal") or "").split("\n")[0][:60]
        agent_lines.append(f"- {aid} | {role} — {goal}" if goal else f"- {aid} | {role}")
    agent_block = "\n".join(agent_lines) if agent_lines else "（无）"

    return template.replace("{available_mcp_servers}", mcp_block).replace(
        "{available_agents}", agent_block,
    )
