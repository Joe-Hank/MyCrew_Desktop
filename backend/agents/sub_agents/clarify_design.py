"""Clarify-design sub-agent — Q&A on existing project / blueprint.

Strictly read-only. No write tools. No DB mutations.

Reads `.mycrew/architecture.md` + `.mycrew/tasks/*.md` from project root
to answer "why is task N designed this way" / "what does X mean" etc.
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


_ROLE = "Plan Maker - Q&A"
_GOAL = "回答用户关于当前项目蓝图/任务设计的问题。不修改任何数据。"

_BACKSTORY = """## 你的工作
回答用户关于他们当前项目蓝图、任务设计、Agent 分配的问题。

## 严格只读
- **不调** create_workflow / assign_agents / write_blueprint / patch_blueprint
- **只调** read_file_local / list_directory_local，读 `<root>/.mycrew/` 目录下的：
  - `blueprint.json` — 完整任务图 + Agent 分配
  - `architecture.md` — 架构总览
  - `tasks/task_NN_*.md` — 每个任务的 detail + acceptance_notes

## 回答风格
- 直接引用 `.mycrew/` 内容
- 简洁，3-5 句话回答完
- 如果用户问"为什么"，结合 architecture.md 的设计理由解释
- 如果 .mycrew/ 里没有相关信息，**坦诚说"找不到"**，不要编造

## 工具协议
1. 先 list_directory_local('.mycrew') 看有什么
2. read_file_local 读相关文件
3. 直接答复用户

不要调写工具。不要回答与项目无关的问题。"""


async def run(user_message: str, session: dict) -> SubAgentResult:
    session_id = session.get("id") or ""

    project_id = session.get("project_id")
    if not project_id:
        return empty_result(
            "还没有创建项目，没有蓝图可查。先用『新建项目』走一遍流程。"
        )

    try:
        provider, model_name = await resolve_session_llm_with_provider(session)
    except ValueError as exc:
        return empty_result(f"⚠️ LLM 配置错误：{exc}")

    from infra.repo import crud
    from src.tools.builtin.local.workspace import make_workspace_tools

    project = await crud.get_by_id("projects", project_id)
    root = project.get("root_path") if project else None
    if not root:
        return empty_result(
            "项目还没设置 root_path，蓝图未持久化到 `.mycrew/`，暂无可查内容。"
        )

    ws = make_workspace_tools(root)
    tools = [ws["read_file_local"], ws["list_directory_local"]]

    description = (
        f"## 用户提问\n{user_message}\n\n"
        "请只读 `.mycrew/` 下的文件来回答。"
    )

    try:
        reply = await run_crewai_agent(
            session_id=session_id,
            role=_ROLE, goal=_GOAL, backstory=_BACKSTORY,
            description=description,
            expected_output="用 3-5 句话直接回答用户的问题，引用 .mycrew/ 里的相关内容。",
            tools=tools,
            provider=provider, model_name=model_name,
            max_iter=3,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("clarify_design.kickoff_failed", error=str(exc),
                  session_id=session_id)
        return empty_result(f"⚠️ 查询失败：{exc}")

    return {
        "reply_text": reply or "（无回复）",
        "project_id": project_id,
        "blueprint": None,
        "metadata": {"sub_agent": "clarify_design"},
    }
