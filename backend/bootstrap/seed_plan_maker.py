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
    "你是 MyCrew Plan Maker，将用户的项目想法转化为可执行的多代理工作流。\n"
    "你必须：(1) 拆解需求为有序的任务列表；(2) 决定 execution_kind "
    "(sequential/crew/flow)；(3) 为每个任务定义合理的 output_schema；"
    "(4) 调用 create_workflow 工具将工作流持久化到数据库。"
)

PLAN_MAKER_BACKSTORY_TEMPLATE = """你具备 MyCrew 平台的完整上下文：

## 可用的 MCP 服务器（集群协调能力）
{available_mcp_servers}

## 可用的执行代理（subordinate agents）
{available_agents}

## 任务编排规则
- 1~2 个任务：使用 sequential
- 3~5 个任务：使用 crew（agents 并行 + 共享上下文）
- 6+ 个任务：使用 flow（图状依赖）
- 必须有一个 kind="final_qa" 的任务作为质检终点（依赖所有终端节点）
- 每个任务的 output_schema 应为合法的 JSON Schema 描述其产出结构
- 当任务需要 MCP（如 blender/unity/comfyui）时，在 detail 中明确点名

## 输出协议
- 不要输出 ```json 代码块。
- 当你认为方案已经成熟，**必须调用 create_workflow 工具**完成持久化。
- 工具调用之前可与用户对话澄清；调用之后会向前端推送 inception.workflow_created 事件。"""


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
    with live DB content. Called by inception_svc at task-construction time."""
    mcp_rows = await crud.get_all("mcp_servers")
    enabled_mcps = [r for r in mcp_rows if r.get("enabled", 1)]
    mcp_lines = []
    for s in enabled_mcps:
        name = s.get("name", "")
        # Use any description field if available; fall back to transport+command hint
        hint = s.get("transport", "") or ""
        mcp_lines.append(f"- {name}" + (f" ({hint})" if hint else ""))
    mcp_block = "\n".join(mcp_lines) if mcp_lines else "（无可用 MCP 服务器）"

    agent_rows = await crud.get_all("agents")
    other_agents = [a for a in agent_rows if a.get("role") != "Plan Maker"]
    agent_lines = []
    for a in other_agents:
        role = a.get("role", "")
        goal = (a.get("goal") or "").split("\n")[0][:80]  # first line, truncated
        agent_lines.append(f"- {role}: {goal}")
    agent_block = "\n".join(agent_lines) if agent_lines else "（无其他可用代理）"

    return template.replace("{available_mcp_servers}", mcp_block).replace(
        "{available_agents}", agent_block,
    )
