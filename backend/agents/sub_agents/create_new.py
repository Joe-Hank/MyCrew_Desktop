"""Create-new sub-agent — handles "make me a new game/project" requests.

Minimal prompt focused ONLY on the create flow:
  - Template skeleton (from session.template_id)
  - 3 mutation tools: create_workflow + assign_agents + write_blueprint
  - Tool-call protocol (3 in sequence then short ack)

Does NOT include iterate-mode rules, Q&A rules, or modify_blueprint rules.
Token target: ~1500 in / 3-8 LLM iter.

Post-kickoff self-heal:
  After the main kickoff returns, we validate the resulting DB+disk state.
  If any of the 3 expected steps (create_workflow / assign_agents /
  write_blueprint) is missing, a focused single-tool repair kickoff fires
  in the background — same session, no user-visible delta broadcasts.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

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
美术建模走 Blender MCP；图像生成走 ComfyUI MCP；**Unity 编辑器操作走 MCP for Unity**
（读写资产 / 执行 C# / 查询场景 / 截图），Unity 操作类 task 的 detail 要明示用 MCP for Unity 工具，
而不是裸 write_file。

# 项目内预置
- `Assets/Fonts/` 已放好常用中文字体；所有中文 TMP/UGUI 文本直接引用，不要让 agent 重新下载/生成字体。

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

    # Tell the frontend the right-side blueprint panel should open NOW
    # with a "drafting" skeleton. Tasks land later via inception.workflow_created;
    # agents land via inception.agents_assigned.
    try:
        from api.ws import manager as _ws_manager
        await _ws_manager.broadcast("inception.drafting_started", {
            "session_id": session_id,
            "intent": "create_new",
            "mode": "create",
        })
    except Exception:
        pass  # best-effort

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
            max_iter=8,
            temperature=DEFAULT_PARAMS["temperature"],
            max_tokens=DEFAULT_PARAMS["max_tokens"],
        )
    except Exception as exc:  # noqa: BLE001
        log.error("create_new.kickoff_failed", error=str(exc),
                  session_id=session_id)
        return empty_result(f"⚠️ Plan Maker 调用失败：{exc}")

    # Post-kickoff detection + self-heal. Only fires for step2/step3
    # gaps; step1 (no project_id) is left to existing error-path code.
    from infra.repo import crud
    refreshed = await crud.get_by_id("inception_sessions", session_id)
    pid = refreshed.get("project_id") if refreshed else None
    repair_suffix = ""
    repair_status = "none"
    if pid:
        gap = await _validate_state(pid)
        if gap.missing_step2 or gap.missing_step3:
            log.info("create_new.repair_kicked",
                     session_id=session_id, project_id=pid,
                     missing_step2=gap.missing_step2,
                     missing_step3=gap.missing_step3)
            try:
                fixed = await _repair_gaps(
                    session_id, pid, gap, provider, model_name,
                )
                # Re-validate post repair
                gap2 = await _validate_state(pid)
                if gap2.missing_step2 or gap2.missing_step3:
                    repair_status = "failed"
                    repair_suffix = (
                        "\n\n⚠️ 自动修复未完全成功，请重发请求或在团队页手动分配 agent。"
                    )
                    log.warning("create_new.repair_failed",
                                session_id=session_id, project_id=pid,
                                still_missing_step2=gap2.missing_step2,
                                still_missing_step3=gap2.missing_step3)
                else:
                    repair_status = "ok"
                    parts: list[str] = []
                    if "step2" in fixed:
                        parts.append("任务分配")
                    if "step3" in fixed:
                        parts.append("蓝图落盘")
                    repair_suffix = f"\n\n（自动补齐了：{' / '.join(parts)}）" if parts else ""
                    log.info("create_new.repair_ok",
                             session_id=session_id, project_id=pid,
                             fixed=list(fixed))
            except Exception as exc:  # noqa: BLE001
                repair_status = "failed"
                repair_suffix = "\n\n⚠️ 自动修复未成功，请重发请求或在团队页手动分配 agent。"
                log.error("create_new.repair_exception",
                          session_id=session_id, project_id=pid,
                          error=str(exc))
    return {
        "reply_text": (reply or "（无回复）") + repair_suffix,
        "project_id": pid,
        "blueprint": None,  # broadcast separately via create_workflow tool's event
        "metadata": {"sub_agent": "create_new", "repair_status": repair_status},
    }


# ── Post-kickoff detection + self-heal ──────────────────────────────


class _StateGap(NamedTuple):
    missing_step1: bool   # project_id 没设
    missing_step2: bool   # 任一 task 缺 agent_id
    missing_step3: bool   # .mycrew/blueprint.json 不存在
    tasks: list[dict]     # 复用给修复 prompt，避免再查一次
    project: dict | None


def _resolve_blueprint_dir(project: dict) -> Path:
    """Mirrors write_blueprint.py:109-116 — keep in sync if that file
    changes the layout rule."""
    from bootstrap.paths import OUTPUT_DIR
    iteration_index = int(project.get("iteration_index") or 1)
    root_path = project.get("root_path") or ""
    if root_path:
        base = Path(root_path) / ".mycrew"
        if iteration_index > 1:
            base = base / f"iter-{iteration_index:03d}"
        return base
    return Path(OUTPUT_DIR) / project["id"] / ".mycrew_pending"


async def _validate_state(project_id: str) -> _StateGap:
    """Pure read. Determines which of the 3 expected steps left no trace."""
    from infra.repo import crud
    project = await crud.get_by_id("projects", project_id)
    if not project:
        return _StateGap(True, False, False, [], None)
    tasks = await crud.get_all("tasks", "project_id = ?", (project_id,))
    missing_step2 = (not tasks) or any(not t.get("agent_id") for t in tasks)
    bp_path = _resolve_blueprint_dir(project) / "blueprint.json"
    missing_step3 = not bp_path.exists()
    return _StateGap(False, missing_step2, missing_step3, list(tasks), project)


async def _repair_gaps(
    session_id: str,
    project_id: str,
    gap: _StateGap,
    provider: dict,
    model_name: str,
) -> set[str]:
    """Run focused single-tool kickoff(s) to fill in missing step2/step3.

    Returns the set of step names that were attempted (and succeeded
    according to the LLM's own report — the outer caller re-validates).
    """
    fixed: set[str] = set()

    if gap.missing_step2:
        await _repair_step2(session_id, gap, provider, model_name)
        fixed.add("step2")

    # Re-fetch tasks after step2 repair so the step3 prompt sees fresh agent_ids
    if gap.missing_step3:
        from infra.repo import crud
        fresh_tasks = await crud.get_all("tasks", "project_id = ?", (project_id,))
        await _repair_step3(session_id, gap.project or {}, fresh_tasks,
                            provider, model_name)
        fixed.add("step3")

    return fixed


async def _repair_step2(
    session_id: str,
    gap: _StateGap,
    provider: dict,
    model_name: str,
) -> None:
    from src.tools.builtin.local.assign_agents import make_assign_agents_tool
    from infra.repo import crud

    # Build the "待分配 task" + "可用 agent" facts pack
    task_lines: list[str] = []
    for i, t in enumerate(gap.tasks):
        title = (t.get("title") or "").strip() or "（未命名）"
        detail = (t.get("detail") or "").replace("\n", " ").strip()[:100]
        task_lines.append(
            f"- task_index={i} | {title}" + (f" — {detail}" if detail else "")
        )

    agent_rows = await crud.get_all("agents")
    agent_lines: list[str] = []
    for a in agent_rows:
        if a.get("role") == "Plan Maker":
            continue
        aid = a.get("id", "")
        role = a.get("role", "")
        goal = (a.get("goal") or "").split("\n")[0][:60]
        agent_lines.append(f"- {aid} | {role} — {goal}")

    backstory = (
        "你是 MyCrew 修复机器人。上一轮项目已建好但 task 还没分配 agent。\n"
        "**只调一次 assign_agents** 把每个 task 配一个最匹配的 agent_id，"
        "调完一句中文确认。不要重新设计任务、不要创建 PM 角色。"
    )
    description = (
        "## 待分配 task\n" + "\n".join(task_lines) + "\n\n"
        "## 可用 agent\n" + ("\n".join(agent_lines) or "（无）") + "\n\n"
        "调用 assign_agents(assignments=[{task_index, existing_agent_id}, ...])。"
    )

    await run_crewai_agent(
        session_id=session_id,
        role="MyCrew 修复机器人",
        goal="补齐 task → agent 的分配，绝不重新设计任务。",
        backstory=backstory,
        description=description,
        expected_output="调一次 assign_agents 后一句中文确认。",
        tools=[make_assign_agents_tool(session_id)],
        provider=provider, model_name=model_name,
        max_iter=3, temperature=0.0, max_tokens=1500,
        broadcast_steps=False,
    )


async def _repair_step3(
    session_id: str,
    project: dict,
    tasks: list[dict],
    provider: dict,
    model_name: str,
) -> None:
    from src.tools.builtin.local.write_blueprint import make_write_blueprint_tool

    task_lines: list[str] = []
    for i, t in enumerate(tasks):
        title = (t.get("title") or "").strip() or "（未命名）"
        agent = t.get("agent_id") or "（未分配）"
        detail = (t.get("detail") or "").replace("\n", " ").strip()[:120]
        task_lines.append(
            f"- {i+1}. {title} | agent={agent}" + (f" — {detail}" if detail else "")
        )

    backstory = (
        "你是 MyCrew 修复机器人。项目 + agent 分配都好了但 .mycrew/ 还没落盘。\n"
        "**只调一次 write_blueprint**：先用 100-300 字概述本项目的目标 + 关键技术决策，"
        "再带上 tasks 调用，调完一句中文确认。不要重新设计任务。"
    )
    description = (
        f"## 项目\n名称：{project.get('name', '(unknown)')}\n\n"
        "## task 列表（已含 agent_id）\n" + "\n".join(task_lines) + "\n\n"
        "调用 write_blueprint(architecture_overview, tasks)。"
    )

    await run_crewai_agent(
        session_id=session_id,
        role="MyCrew 修复机器人",
        goal="补齐 .mycrew/ 蓝图落盘，绝不重新设计任务。",
        backstory=backstory,
        description=description,
        expected_output="调一次 write_blueprint 后一句中文确认。",
        tools=[make_write_blueprint_tool(session_id)],
        provider=provider, model_name=model_name,
        max_iter=3, temperature=0.3, max_tokens=2500,
        broadcast_steps=False,
    )


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
