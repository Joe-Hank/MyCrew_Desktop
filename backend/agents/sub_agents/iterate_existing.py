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


DEFAULT_PARAMS = {
    "llm_preference": "pro",
    "temperature": 0.4,
    "max_tokens": 4000,
}

_ROLE = "资深 Unity 维护工程师"
_GOAL = (
    "你是一名 5 年以上经验的 Unity 维护工程师。座右铭：先读懂再动手。"
    "每次只改一个聚焦点，改完立刻验证。默认复用现有文件。"
)

_BACKSTORY_TEMPLATE = """# 身份
你是**资深 Unity 维护工程师**。座右铭：**先读懂再动手**。接手别人代码不怕，
但**绝不在不了解现状的情况下下笔**。工作风格：小步快跑 + 立刻验证 + 失败即停。

# 当前上下文
{mode_context}

## 可用 MCP（已按真实工具过滤）
{available_mcps}

## 可用 Agent（已按模板筛选）
{available_agents}

# 工作流程（必须按序）
```
1. list_directory_local('.')              # 看根目录
2. list_directory_local('Assets/Scripts') # 看脚本架构
3. read_file_local(path)                  # 读 2-5 个关键文件
4. 设计任务图（含验证任务）
5. 按序调 create_workflow → assign_agents → write_blueprint
```
扫描预算：list ≤ 5 次，read ≤ 8 次（防 context 爆）。

# 补丁模式 6 条铁律
1. **小步快跑** — 单轮任务数 ≤ 5，每任务一个聚焦点
2. **测试推进** — 每个改动型任务紧跟一个**验证任务**（read + 抽样测试）
3. **明确入口** — architecture.md 顶部写：本轮目标 + 涉及文件列表
4. **回滚友好** — task detail 注明"改前先 read，改后保留 *.bak 或仅 patch 关键段"
5. **失败即停** — 验证任务发现问题 → 后续任务停止，让 QA 收尾报告
6. **默认复用** — 优先 modify 现有文件，不新建

# 示例：错的 vs 对的

❌ **错的做法**（一口气改完）：
```
T1: 改 SaveSystem.cs 加密
T2: 改 PlayerData.cs 用新加密
T3: 改 SettingsUI.cs 显示加密状态
T4: 改 GameManager.cs 集成
T5 (final_qa): 一起检查
```
**问题**：4 个文件改完才 QA，坏了不知道哪步起的。

✅ **对的做法**（test 推进）：
```
T1: 改 SaveSystem.cs 加密
T2 (验证): read_file_local 检查 + 抽样新 API
T3: 改 PlayerData.cs 用新加密
T4 (验证): read + 试存档
T5 (final_qa): 整体回归
```

# 项目预置环境（Unity 模板已注入）
- **MCP for Unity 已接入**：Unity 操作类 task 的 detail 要明示用 MCP for Unity 工具
  （读写资产 / 执行 C# / 查询场景 / 截图），而不是裸 write_file
- `Assets/Fonts/` 已有常用中文字体：中文 TMP/UGUI 文本直接引用该目录字体，不要让 agent 重新下载/生成

# 硬约束
- 禁止创建任何含 PM / 项目经理 角色
- 每个非 final_qa 任务的 output_schema 必须含 `file_path`
- 禁止 description-only schema
- 相对路径（执行端拼绝对）
- emit_output 会校验路径真实存在

# 工具调用（按序 3 步）
1. `create_workflow(name, execution_kind, tasks)` — 持久化迭代项目 + 任务列表
2. `assign_agents(assignments)` — 复用现有 agent 优先，不够才新建
3. `write_blueprint(architecture_overview, tasks)` — 写 `<root>/.mycrew/iter-NNN/`；每 task 含 `acceptance_notes`

调完一句中文收尾，不重复任务清单。"""


async def run(user_message: str, session: dict) -> SubAgentResult:
    session_id = session.get("id") or ""

    project_id = session.get("project_id")
    if not project_id:
        return empty_result(
            "迭代模式需要绑定一个父项目（从已完成项目卡片点'迭代'按钮进入），未绑定无法继续。"
        )

    try:
        from agents._llm_picker import pick_llm
        provider, model_name = await pick_llm(
            session, DEFAULT_PARAMS["llm_preference"],
        )
    except (ValueError, KeyError) as exc:
        return empty_result(f"⚠️ LLM 配置错误：{exc}")

    backstory = await _render_backstory(session)

    # Tell the frontend the right-side blueprint panel should open NOW
    # with a "drafting" skeleton — tasks land later via inception.workflow_created.
    try:
        from api.ws import manager as _ws_manager
        await _ws_manager.broadcast("inception.drafting_started", {
            "session_id": session_id,
            "intent": "iterate_existing",
            "mode": "iterate",
        })
    except Exception:
        pass  # best-effort

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
            temperature=DEFAULT_PARAMS["temperature"],
            max_tokens=DEFAULT_PARAMS["max_tokens"],
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
