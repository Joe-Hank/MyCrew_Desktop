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
    "MyCrew Plan Maker：把用户的项目设计需求拆成可执行任务流并持久化。"
    "架构规划归你（不拆给后置 PM）。非项目话题礼貌拒绝。"
)

PLAN_MAKER_BACKSTORY_TEMPLATE = """## 上下文
{mode_context}

## 可用 MCP
{available_mcp_servers}

## 可用 Agent（已按模板筛选）
{available_agents}

## 硬约束
- 你独自做架构规划。**禁止**创建/调用任何含 "Project Manager / 项目经理 / PM"
  的执行 Agent；架构思考写进 architecture.md
- 每个非 final_qa 任务的 output_schema 必须含 `file_path`（项目相对路径）
  + 可选 `summary`。**禁止 description-only schema**（无 file_path = 拒收）
- file_path 一律用相对路径（与 root_path 设置时机解耦）；执行端 workspace
  工具自动拼绝对路径
- emit_output **会校验** file_path 真实存在，骗不过去
- task detail 必须明文指令执行 Agent："先用 write_file/unity_write_file/
  comfy_enqueue_workflow 把文件创建到 <相对路径>，再调 emit_output 报告路径"

## 编排
- 任务数 1-2→sequential，3-5→crew，6+→flow
- 末尾必须 kind="final_qa"，deps 指向所有终端节点
- output_schema 是合法 JSON Schema；`{}` 表示自由文本

## 默认技术栈
游戏/3D/VR/AR/交互 → **Unity 2022 LTS + C# + URP + Input System + UGUI**
（禁默认 Web/Python 游戏栈，除非用户明确指定）。
美术建模走 Blender MCP；图像生成走 ComfyUI MCP。

## 模式分流
- **create + Unity 模板**：按模板目录骨架设计完整子系统
- **create + 空模板**：暂仍按 Unity 思路，architecture.md 标注"类型可能非 Unity"
- **iterate（补丁模式，重要）**：
  1. 单轮任务 ≤ 5，每个任务改一个聚焦点
  2. 每个改动任务后紧跟**验证任务**（read 关键文件确认未破坏旧功能）
  3. architecture.md 顶部写本轮目标 + 涉及文件列表
  4. 修改前 read_file_local 查原内容；保留 .bak 或仅 patch 关键段
  5. 验证失败 → **后续任务停止**，让 QA 收尾报告
  6. 默认 modify 现有文件，不新建

## 何时澄清
默认直接产出（俄罗斯方块/Snake 等著名原型按合理默认假设立即调工具）。
只在输入极度抽象（"做个项目"）时提 1 个澄清问题。

## 范围限制
非项目设计请求 → 不调工具，回复：「（不在项目立项范围）— 我只能帮你拆解
项目任务。请描述具体项目，如『做一个 Unity 平台跳跃游戏，三关，每关有 boss』」

## 工具调用（严格按序，3 步）
方案明确时**必须依次调**：
1. `create_workflow(name, execution_kind, tasks)` — 持久化
2. `assign_agents(assignments)` — `existing_agent_id` 复用 / `new_agent{role,goal,backstory}` 新建（role 例: "Unity 客户端工程师"）
3. `write_blueprint(architecture_overview, tasks)` — 写 `<root>/.mycrew/`；tasks 与 step 1 同结构，但每项多一个 `acceptance_notes`（"怎么验证算 OK"）

调完 3 步立刻**一句中文**收尾（例: "任务方案已生成，N 个 task，新建 M 个 agent"），
不再列任务、不重复、不思考下一步、不输出 ```json 块。"""


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
    assign_agents_id = tool_name_to_id.get("assign_agents")
    write_blueprint_id = tool_name_to_id.get("write_blueprint")
    if not create_workflow_id:
        log.warning("seed.plan_maker.no_create_workflow_tool")

    # Plan Maker's full toolchain: create_workflow → assign_agents → write_blueprint
    desired_tool_ids = [
        tid for tid in (create_workflow_id, assign_agents_id, write_blueprint_id)
        if tid
    ]

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

    # Always ensure the full toolchain is in tool_ids (idempotent)
    merged = list(existing_tool_ids)
    added_any = False
    for tid in (create_workflow_id, assign_agents_id, write_blueprint_id):
        if tid and tid not in merged:
            merged.append(tid)
            added_any = True
    if added_any:
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

# Template-id → 与之相关的 agent role 关键词。Plan Maker 收到的可用
# agent 列表会按这些关键词打分，只保留 top N（见 _AGENT_LIST_CAP）。
# 避免把 16 个 agent 全塞进上下文（旧实现 ~600 tokens 每轮）。
_TEMPLATE_AGENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "unity_universal_2d": (
        "unity", "2d", "sprite", "platformer", "ui", "ux",
        "narrative", "art", "concept", "audio", "system", "qa",
    ),
    "unity_universal_3d": (
        "unity", "3d", "model", "shader", "art", "concept",
        "vfx", "animator", "audio", "system", "qa",
    ),
    "unity_ar_mobile": (
        "unity", "ar", "xr", "3d", "model", "ui", "ux",
        "shader", "qa", "art",
    ),
    "unity_mr_core": (
        "unity", "mr", "xr", "3d", "model", "ui", "ux",
        "shader", "qa", "art",
    ),
    "blank": (),  # 空模板不过滤，全部展示（让 Plan Maker 自己挑）
}

# Roles always worth showing regardless of relevance score — QA agent in
# particular is required by the final_qa task contract.
_AGENT_ALWAYS_KEEP = ("qa engineer", "qa-agent", "reviewer")
_AGENT_LIST_CAP = 8


def _score_agent_relevance(agent: dict, keywords: tuple[str, ...]) -> int:
    """How many template keywords appear in this agent's role+goal."""
    text = ((agent.get("role") or "") + " " + (agent.get("goal") or "")).lower()
    return sum(1 for kw in keywords if kw in text)


def _filter_agents_for_prompt(
    agents: list[dict], template_id: str | None,
) -> list[dict]:
    """Return up to _AGENT_LIST_CAP agents, ranked by template relevance.

    If template is unknown or "blank", returns the full list capped at cap
    (so iteration on legacy projects still works). Always-keep agents
    (QA etc.) are guaranteed to be included if present."""
    if not template_id or template_id not in _TEMPLATE_AGENT_KEYWORDS:
        return agents[:_AGENT_LIST_CAP]
    keywords = _TEMPLATE_AGENT_KEYWORDS[template_id]
    if not keywords:
        return agents[:_AGENT_LIST_CAP]

    must_keep: list[dict] = []
    rest: list[dict] = []
    for a in agents:
        role_l = (a.get("role") or "").lower()
        if any(k in role_l for k in _AGENT_ALWAYS_KEEP):
            must_keep.append(a)
        else:
            rest.append(a)

    rest.sort(key=lambda a: _score_agent_relevance(a, keywords), reverse=True)
    slots_left = _AGENT_LIST_CAP - len(must_keep)
    return must_keep + rest[:max(0, slots_left)]


async def render_plan_maker_backstory(
    template: str,
    session: dict | None = None,
) -> str:
    """Replace placeholders with live DB content + session context.

    Placeholders:
      - {available_mcp_servers}, {available_agents}: enabled MCPs / non-PM agents
      - {mode_context}: per-session mode-specific block (template structure
        for create mode, root_path summary for iterate mode)

    Agent list is FILTERED by template relevance (see
    _filter_agents_for_prompt) — old impl dumped all 16, ate ~600 tokens.
    Each entry includes the `id` so Plan Maker can use it directly via
    `assign_agents.existing_agent_id`.
    """
    # MCP listing strategy (per 2026-05-15 prompt audit discussion):
    #   - Only include MCPs that have *successfully discovered tools at
    #     least once* (discovered_tools non-empty) — filters out dead
    #     servers that show enabled=1 but the process never came up
    #   - Show each MCP's actual tool names so Plan Maker stops guessing
    #     capabilities from server names (e.g. "blender" = ?). Cap at
    #     10 names + show total count so big MCPs don't blow up tokens.
    mcp_rows = await crud.get_all("mcp_servers")
    enabled_mcps = [r for r in mcp_rows if r.get("enabled", 1)]
    TOOL_CAP_PER_MCP = 10
    mcp_lines: list[str] = []
    for s in enabled_mcps:
        name = s.get("name") or ""
        if not name:
            continue
        raw = s.get("discovered_tools") or "[]"
        try:
            tools = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            tools = []
        tool_names = [t.get("name") for t in tools
                       if isinstance(t, dict) and t.get("name")]
        if not tool_names:
            continue  # skip dead / never-connected MCPs
        shown = tool_names[:TOOL_CAP_PER_MCP]
        extra = len(tool_names) - len(shown)
        suffix = f" …+{extra}" if extra > 0 else ""
        mcp_lines.append(f"- {name}: {' / '.join(shown)}{suffix}")
    mcp_block = "\n".join(mcp_lines) if mcp_lines else "（无连通的 MCP）"

    agent_rows = await crud.get_all("agents")
    other_agents = [a for a in agent_rows if a.get("role") != "Plan Maker"]
    template_id = (session or {}).get("template_id")
    filtered = _filter_agents_for_prompt(other_agents, template_id)
    agent_lines = []
    for a in filtered:
        aid = a.get("id", "")
        role = a.get("role", "")
        goal = (a.get("goal") or "").split("\n")[0][:60]
        agent_lines.append(f"- {aid} | {role} — {goal}" if goal else f"- {aid} | {role}")
    if len(filtered) < len(other_agents):
        agent_lines.append(
            f"（已按模板相关性筛选；总计 {len(other_agents)} 个 agent，"
            f"如需其它角色请调 list_agents 工具）"
        )
    agent_block = "\n".join(agent_lines) if agent_lines else "（无）"

    mode_block = await _render_mode_context(session or {})

    return (
        template
        .replace("{mode_context}", mode_block)
        .replace("{available_mcp_servers}", mcp_block)
        .replace("{available_agents}", agent_block)
    )


async def _render_mode_context(session: dict) -> str:
    """Build the per-session mode_context block.

    Create mode + template_id known → render the Unity template skeleton.
    Iterate mode + project_id+root_path known → render a brief scan
    summary (deep scan deferred to a future iteration; for now we just
    surface the path + the parent's template + a "reuse-first" reminder).
    """
    mode = (session.get("mode") or "create").lower()

    if mode == "create":
        template_id = session.get("template_id")
        if not template_id:
            return "## 工作模式: 创建（用户尚未选模板，等待中）"
        from data.unity_templates import render_template_context
        rendered = render_template_context(template_id)
        if not rendered:
            return f"## 工作模式: 创建（未知模板 {template_id}）"
        return f"## 工作模式: 创建新项目\n\n{rendered}"

    if mode in ("iterate", "iterate_external"):
        project_id = session.get("project_id")
        if not project_id:
            return "## 工作模式: 迭代（项目未绑定，无法继续）"
        project = await crud.get_by_id("projects", project_id)
        if not project:
            return f"## 工作模式: 迭代（找不到项目 {project_id}）"
        root_path = project.get("root_path") or "（未设置）"
        template_id = project.get("template_id") or "（未知）"
        iter_idx = int(project.get("iteration_index") or 1)
        parent = project.get("parent_project_id") or "（无）"

        lines = [
            f"## 工作模式: 迭代项目 (第 {iter_idx} 轮)",
            f"项目根目录: {root_path}",
            f"原始模板: {template_id}",
            f"父项目: {parent}",
            "",
            "**复用原则**: 默认引用现有 Assets/Scripts、Prefabs、Scenes、",
            "ScriptableObjects 等已有资产，仅在必须时新建。设计任务时优先",
            "考虑'扩展/修订'而非'从零重写'。",
            "",
            "**你已获得读文件工具** (仅迭代模式启用):",
            "- `list_directory_local(path)` — 列项目下任意目录的子项 (path='.' 看根)",
            "- `read_file_local(path)` — 读单个文件内容（含截断）",
            "",
            "**强烈建议先扫一遍再设计**：典型路径",
            "  1. list_directory_local('.') → 看顶层有什么",
            "  2. list_directory_local('Assets/Scripts') → 看现有脚本架构",
            "  3. 对关键脚本调 read_file_local 看接口签名/数据结构",
            "  4. 再设计任务，task detail 里点名现有文件 → 让执行 Agent 在此",
            "     基础上 modify 或新增",
            "扫描预算：list 最多 5 次、read 最多 8 次，避免 context 爆。",
        ]
        return "\n".join(lines)

    return "## 工作模式: 未指定"
