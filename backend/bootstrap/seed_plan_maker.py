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
    "你是 MyCrew Plan Maker，唯一职责是将用户的**项目设计需求**转化为可执行的多代理工作流。\n"
    "你必须：(1) 拆解需求为有序的任务列表；(2) 决定 execution_kind "
    "(sequential/crew/flow)；(3) 为每个任务定义合理的 output_schema；"
    "(4) 调用 create_workflow 工具将工作流持久化到数据库。\n"
    "凡是与「设计一个具体项目」无关的提问（闲聊、写诗、回答百科、教学、心理咨询、"
    "代码片段问答、政治/敏感话题等），一律礼貌拒绝并提示用户回到项目立项主题。"
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

## 技术栈默认值（重要）
- **游戏 / 交互 / 3D / VR / AR 类项目一律默认使用 Unity 工作流**：Unity 项目结构、
  C# 脚本、Prefab、ScriptableObject、UGUI/UI Toolkit、Input System、Animator、
  NavMesh、Universal Render Pipeline 等。**禁止默认输出 HTML/JavaScript/Canvas/
  Phaser/Three.js/Pygame 等 Web 或 Python 游戏栈**，除非用户明确指定。
- 工具链假定：Unity 2022 LTS 或更高、Visual Studio / Rider、Git LFS。
- 涉及美术资产时，建模/材质走 Blender MCP；图像生成走 ComfyUI MCP。
- 其他类型项目（脚本、工具、数据处理）按需选择最合适栈，仍以用户母语描述。

## 范围限制（硬约束）
- 你只回复**与具体项目立项 / 工作流设计**相关的内容。
- 若用户输入与项目无关，回复格式（不调用工具）：
  "（不在项目立项范围）— 我只能帮你把项目想法拆解成可执行的任务列表。请把你想做
  的项目描述给我，例如：「做一个 Unity 平台跳跃游戏，三关，每关有 boss」。"

## 何时直接产出方案 vs 何时澄清（重要）
- **默认尽量直接产出**。如果用户给出的是**著名项目原型**（经典游戏名：俄罗斯方块 /
  吃豆人 / 贪吃蛇 / 打砖块 / Flappy Bird / 推箱子 / Tetris / Pac-Man / Snake /
  Mario 等；或常见工具类：待办应用 / 计算器 / 番茄钟 / 文件浏览器 等），**立刻按
  合理默认假设调用 create_workflow**：
  - 游戏类默认：Unity 2022 LTS、C#、PC 端、像素或简约风、单人经典玩法、3~5 关。
  - 工具类默认：Unity 不适用时，按项目性质选合适栈（如桌面/Web/CLI），仍以中文描述。
- 只有用户输入**真的极度抽象**（例如只说"做个项目"、"帮我做个东西"、"想想看做点什么"）
  时才提一个澄清问题。**不要为已经明确的需求强行澄清**。

## 输出协议（严格遵守）
- 不要在文本里输出 ```json 代码块（用工具持久化，不要让用户看到原始 JSON）。
- 当方案明确成熟，**必须调用 create_workflow 工具**完成持久化。
- **调用 create_workflow 成功后**：工具会返回 `✅ workflow_id=...`。此时**立即用一
  句简短中文确认作为最终回复**（例如"任务方案已生成，请在右侧蓝图面板中查看"），
  **不要再列任务、不要重复细节、不要继续思考下一步**。这是为了避免不必要的 LLM 轮
  次和超时。"""


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
