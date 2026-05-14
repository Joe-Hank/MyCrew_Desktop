"""Iterate-existing sub-agent — patch-mode on an existing project root.

Differs from create_new:
  - Has read_file_local + list_directory_local (bound to project root)
  - Prompt is "patch mode": small steps + verification tasks + reuse-first
  - Designed to produce ≤5 tasks per round, each with a follow-up verify

Token target: ~1800 in / 5-7 LLM iter.
"""
from __future__ import annotations

import structlog

from agents.sub_agents._base import (
    SubAgentResult,
    empty_result,
    resolve_session_llm_with_provider,
    run_crewai_agent,
)

log = structlog.get_logger()


_ROLE = "Plan Maker - Iterate"
_GOAL = (
    "在已有 Unity 项目上小步快跑地打补丁。每次改动后紧跟验证任务。"
    "默认复用现有文件，避免重写。"
)

_BACKSTORY_TEMPLATE = """## 上下文
{mode_context}

## 可用 MCP（已按真实工具过滤）
{available_mcps}

## 可用 Agent（已按模板筛选）
{available_agents}

## 补丁模式 6 条铁律
1. **小步快跑** — 单轮任务数 ≤ 5，每个任务改一个聚焦点
2. **测试推进** — 每个改动型任务后**必须紧跟一个验证任务**：读关键文件 / 对比上一版，确认未破坏旧功能
3. **明确入口** — architecture.md 顶部写：本轮目标 + 涉及文件列表
4. **回滚友好** — task detail 写明"修改前先 read_file_local 看原内容，write_file 时保留 *.bak 备份或仅 patch 关键段"
5. **失败即停** — 验证任务发现问题 → 后续任务停止推进，让 QA 收尾报告
6. **默认复用** — 优先 modify 现有文件，不新建；调 list_directory_local + read_file_local 先确认现有结构

## 工作流程
1. 调 `list_directory_local('.')` 看顶层
2. 必要时 `list_directory_local('Assets/Scripts')` 等看子目录
3. 必要时 `read_file_local(path)` 看关键文件签名（最多 8 次，避免 context 爆）
4. 设计任务图（含验证任务，遵循上述 6 条铁律）
5. 按序调 3 个工具：create_workflow → assign_agents → write_blueprint

## 硬约束
- **禁止**创建/调用任何含 "Project Manager / 项目经理 / PM" 的执行 Agent
- 每个非 final_qa 任务的 output_schema 必须含 `file_path`（项目相对路径）+ 可选 `summary`
- **禁止 description-only schema**
- file_path 一律用相对路径
- emit_output **会校验** file_path 真实存在

## 工具调用（按序 3 步）
1. `create_workflow(name, execution_kind, tasks)` — 持久化迭代项目 + 任务列表
2. `assign_agents(assignments)` — `existing_agent_id` 复用 / `new_agent{...}` 新建
3. `write_blueprint(architecture_overview, tasks)` — 写 `<root>/.mycrew/iter-NNN/`；每 task 加 `acceptance_notes`

调完一句中文收尾，不再列任务、不重复、不输出 ```json 块。"""


async def run(user_message: str, session: dict) -> SubAgentResult:
    session_id = session.get("id") or ""

    project_id = session.get("project_id")
    if not project_id:
        return empty_result(
            "迭代模式需要绑定一个父项目（从已完成项目卡片点'迭代'按钮进入），未绑定无法继续。"
        )

    try:
        provider, model_name = await resolve_session_llm_with_provider(session)
    except ValueError as exc:
        return empty_result(f"⚠️ LLM 配置错误：{exc}")

    backstory = await _render_backstory(session)

    from src.tools.builtin.local.create_workflow import make_create_workflow_tool
    from src.tools.builtin.local.assign_agents import make_assign_agents_tool
    from src.tools.builtin.local.write_blueprint import make_write_blueprint_tool
    from src.tools.builtin.local.workspace import make_workspace_tools
    from infra.repo import crud

    extra_tools: list = []
    project = await crud.get_by_id("projects", project_id)
    root = project.get("root_path") if project else None
    if root:
        ws = make_workspace_tools(root)
        extra_tools.extend([ws["read_file_local"], ws["list_directory_local"]])
    else:
        return empty_result(
            "父项目未设置 root_path，无法扫工作区。请先在项目卡片配置路径。"
        )

    tools = [
        make_create_workflow_tool(session_id),
        make_assign_agents_tool(session_id),
        make_write_blueprint_tool(session_id),
        *extra_tools,
    ]

    description = (
        f"## 用户迭代需求\n{user_message}\n\n"
        "先用工作区读工具扫现状，再设计 ≤5 个任务（含验证），然后按序调 3 个工具收尾。"
    )

    try:
        reply = await run_crewai_agent(
            session_id=session_id,
            role=_ROLE, goal=_GOAL, backstory=backstory,
            description=description,
            expected_output="先 list+read 扫现状，再依次调 3 个工具，最后一句中文收尾。",
            tools=tools,
            provider=provider, model_name=model_name,
            max_iter=7,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("iterate_existing.kickoff_failed", error=str(exc),
                  session_id=session_id)
        return empty_result(f"⚠️ Plan Maker 调用失败：{exc}")

    refreshed = await crud.get_by_id("inception_sessions", session_id)
    pid = refreshed.get("project_id") if refreshed else None
    return {
        "reply_text": reply or "（无回复）",
        "project_id": pid,
        "blueprint": None,
        "metadata": {"sub_agent": "iterate_existing"},
    }


async def _render_backstory(session: dict) -> str:
    """Same renderer as create_new — share via duck-typed call."""
    from agents.sub_agents.create_new import _render_backstory as create_render
    rendered = await create_render(session)
    # Swap out the backstory body but keep the {mode_context}/{mcps}/{agents}
    # already filled. Simpler approach: build it natively with our own template.
    from bootstrap.seed_plan_maker import (
        _filter_agents_for_prompt,
        _render_mode_context,
    )
    from infra.repo import crud
    import json

    mode_context = await _render_mode_context(session)
    mcp_rows = await crud.get_all("mcp_servers")
    enabled_mcps = [r for r in mcp_rows if r.get("enabled", 1)]
    mcp_lines: list[str] = []
    for s in enabled_mcps:
        name = s.get("name") or ""
        raw = s.get("discovered_tools") or "[]"
        try:
            tools = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            tools = []
        names = [t.get("name") for t in tools if isinstance(t, dict) and t.get("name")]
        if not names:
            continue
        shown = names[:10]
        extra = len(names) - len(shown)
        suffix = f" …+{extra}" if extra > 0 else ""
        mcp_lines.append(f"- {name}: {' / '.join(shown)}{suffix}")
    mcp_block = "\n".join(mcp_lines) if mcp_lines else "（无连通的 MCP）"

    agent_rows = await crud.get_all("agents")
    other = [a for a in agent_rows if a.get("role") != "Plan Maker"]
    filtered = _filter_agents_for_prompt(other, session.get("template_id"))
    agent_lines = [
        f"- {a.get('id','')} | {a.get('role','')} — "
        f"{(a.get('goal') or '').split(chr(10))[0][:60]}"
        for a in filtered
    ]
    agent_block = "\n".join(agent_lines) if agent_lines else "（无）"

    _ = create_render  # suppress unused warning; we keep the alt path for ref
    return (
        _BACKSTORY_TEMPLATE
        .replace("{mode_context}", mode_context)
        .replace("{available_mcps}", mcp_block)
        .replace("{available_agents}", agent_block)
    )
