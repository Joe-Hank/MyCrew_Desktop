"""Create-new sub-agent — handles "make me a new game/project" requests.

Minimal prompt focused ONLY on the create flow:
  - Template skeleton (from session.template_id)
  - 3 mutation tools: create_workflow + assign_agents + write_blueprint
  - Tool-call protocol (3 in sequence then short ack)

Does NOT include iterate-mode rules, Q&A rules, or modify_blueprint rules.
Token target: ~1500 in / 3-5 LLM iter.
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
    "temperature": 0.7,
    "max_tokens": 4000,
}

_ROLE = "Unity 游戏架构师"
_GOAL = (
    "你是用户雇佣的 Unity 游戏架构师。"
    "把模糊的项目需求拆成 5-10 个可执行任务，每个任务都有清晰的交付物。"
    "你独自负责架构规划，不创建后置 PM 角色。"
)

_BACKSTORY_TEMPLATE = """# 身份
你是一名 Unity 游戏架构师，对模板系统、Prefab、ScriptableObject、URP/UGUI、Input System 等
Unity 现代工程范式都很熟。你**直接产出方案**，不在简单需求上反复澄清。

# 当前上下文
{mode_context}

## 可用 MCP（已按真实工具过滤）
{available_mcps}

## 可用 Agent（已按模板筛选）
{available_agents}

# 硬约束
- 你独自做架构规划。**禁止**创建任何含 "Project Manager / 项目经理 / PM" 的执行 Agent
- 每个非 final_qa 任务的 output_schema 必须含 `file_path`（项目相对路径）+ 可选 `summary`
- **禁止 description-only schema**（缺 file_path 会被 emit_output 拒收）
- 路径一律相对路径；workspace 工具自动拼绝对路径
- emit_output **会校验** file_path 真实存在，编路径不会得逞
- task detail 必须明文指令执行 Agent："先用 write_file/unity_write_file/comfy_enqueue_workflow
  把文件创建到 <相对路径>，再调 emit_output 报告路径"

# 编排
- 任务数 1-2→sequential，3-5→crew，6+→flow
- 末尾必须 kind="final_qa"，deps 指向所有终端节点
- output_schema 必须是合法 JSON Schema

# 默认技术栈
游戏/3D/VR/AR/交互 → Unity 2022 LTS + C# + URP + Input System + UGUI。
美术建模走 Blender MCP；图像生成走 ComfyUI MCP。

# 何时澄清
默认直接产出（俄罗斯方块 / Snake / Pac-Man 等知名原型按合理默认立即调工具）。
只在需求极度抽象（"做个项目"无任何细节）时提 1 个澄清问题。

# 示例：好的任务图（吃豆人复刻，简化版）

```
Task1: 实现 Player 控制
  agent: Unity 客户端工程师
  output_schema: { file_path: "Assets/Scripts/Player/PacmanController.cs" }
  detail: "用 write_file 创建一个 MonoBehaviour，处理 4 向移动 + 转弯队列，
           按帧消费 Input System..."
  acceptance_notes: "QA 用 read_file_local 检查文件存在且包含 Move() 方法"

Task2: 实现 Ghost AI
  deps: [0]
  output_schema: { file_path: "Assets/Scripts/Ghosts/GhostAI.cs" }
  ...

Task3: 实现关卡数据
  output_schema: { file_path: "Assets/ScriptableObjects/Level01.asset" }
  ...

Task4 (final_qa): 整体质检
  kind: final_qa
  output_schema: { verdict, overall_score, issues, summary }
```

# 工具调用（按序 3 步，每个工具只调 1 次）
1. `create_workflow(name, execution_kind, tasks)` — 持久化项目 + 任务列表
2. `assign_agents(assignments)` — `existing_agent_id` 复用 / `new_agent{role,goal,backstory}` 新建
3. `write_blueprint(architecture_overview, tasks)` — 写 `<root>/.mycrew/`；每 task 加 `acceptance_notes`

调完 3 步立刻一句中文收尾（例: "已生成 5 个任务，新建 2 个 agent"），
不重复任务清单、不输出 ```json 块。"""


async def run(user_message: str, session: dict) -> SubAgentResult:
    """Entry point invoked by router."""
    session_id = session.get("id") or ""

    # Hard precondition (router should have caught this, but defense in depth)
    if (session.get("mode") or "create").lower() == "create" and not session.get("template_id"):
        return empty_result(
            "请先在上方卡片中选择一个 Unity 模板，我才能设计具体任务。"
        )

    try:
        from agents._llm_picker import pick_llm
        provider, model_name = await pick_llm(
            session, DEFAULT_PARAMS["llm_preference"],
        )
    except (ValueError, KeyError) as exc:
        return empty_result(f"⚠️ LLM 配置错误：{exc}")

    backstory = await _render_backstory(session)

    # Bind the 3 mutation tools — same factories the old monolithic agent used
    from src.tools.builtin.local.create_workflow import make_create_workflow_tool
    from src.tools.builtin.local.assign_agents import make_assign_agents_tool
    from src.tools.builtin.local.write_blueprint import make_write_blueprint_tool

    tools = [
        make_create_workflow_tool(session_id),
        make_assign_agents_tool(session_id),
        make_write_blueprint_tool(session_id),
    ]

    # Stateless: we ONLY feed user_message, not history
    description = (
        f"## 用户需求\n{user_message}\n\n"
        "请按『工具调用』段的 3 步顺序调用工具，然后一句中文收尾。"
    )

    try:
        reply = await run_crewai_agent(
            session_id=session_id,
            role=_ROLE, goal=_GOAL, backstory=backstory,
            description=description,
            expected_output="依次调 create_workflow + assign_agents + write_blueprint 三个工具，然后一句中文确认收尾。",
            tools=tools,
            provider=provider, model_name=model_name,
            max_iter=5,
            temperature=DEFAULT_PARAMS["temperature"],
            max_tokens=DEFAULT_PARAMS["max_tokens"],
        )
    except Exception as exc:  # noqa: BLE001
        log.error("create_new.kickoff_failed", error=str(exc),
                  session_id=session_id)
        return empty_result(f"⚠️ Plan Maker 调用失败：{exc}")

    # Check if create_workflow actually persisted anything (project_id flipped)
    from infra.repo import crud
    refreshed = await crud.get_by_id("inception_sessions", session_id)
    pid = refreshed.get("project_id") if refreshed else None
    return {
        "reply_text": reply or "（无回复）",
        "project_id": pid,
        "blueprint": None,  # broadcast separately via create_workflow tool's event
        "metadata": {"sub_agent": "create_new"},
    }


async def _render_backstory(session: dict) -> str:
    """Reuse the existing template-context + filtered agents + MCP renderers."""
    from bootstrap.seed_plan_maker import (
        _filter_agents_for_prompt,
        _render_mode_context,
    )
    from infra.repo import crud
    import json

    mode_context = await _render_mode_context(session)

    # MCPs with real tools, top 10 each (mirrors logic in seed_plan_maker)
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

    # Agents filtered by template
    agent_rows = await crud.get_all("agents")
    other = [a for a in agent_rows if a.get("role") != "Plan Maker"]
    filtered = _filter_agents_for_prompt(other, session.get("template_id"))
    agent_lines = []
    for a in filtered:
        aid = a.get("id", "")
        role = a.get("role", "")
        goal = (a.get("goal") or "").split("\n")[0][:60]
        agent_lines.append(f"- {aid} | {role} — {goal}" if goal else f"- {aid} | {role}")
    if len(filtered) < len(other):
        agent_lines.append(
            f"（已按模板筛选；总计 {len(other)} 个，如需其它角色可在团队页新建）"
        )
    agent_block = "\n".join(agent_lines) if agent_lines else "（无）"

    return (
        _BACKSTORY_TEMPLATE
        .replace("{mode_context}", mode_context)
        .replace("{available_mcps}", mcp_block)
        .replace("{available_agents}", agent_block)
    )
