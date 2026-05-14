"""Modify-blueprint sub-agent — edit a not-yet-started project's task list.

Operates on the DRAFT blueprint — projects in `state='ready'` whose tasks
haven't started yet. User asks to "add a task" / "delete X" / "rename to Y";
this sub-agent uses the `patch_blueprint` tool to apply ops.

Token target: ~700 in / 2-4 LLM iter.
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


_ROLE = "Plan Maker - Edit Draft"
_GOAL = "在用户的草稿蓝图上做精确微调（增删改任务、改 agent 分配）。"

_BACKSTORY = """## 你的工作
在用户的**未启动项目**草稿蓝图上做精确微调。可用操作：

- add_task     新增一个任务
- remove_task  删除任务（按 task_index 或 task_id）
- update_task  改某 task 的字段（title / detail / output_schema / kind 等）
- reorder      重排任务顺序
- assign_agent 改某 task 的 agent_id

## 工具
- `patch_blueprint(ops)` — 唯一写工具，应用一组 ops
  - 仅作用于 state='ready' 的项目（未启动）
  - ops 形如 [{op:"update_task", task_id:"...", patch:{title:"..."}}, ...]
- `read_file_local` / `list_directory_local` — 必要时读 `.mycrew/` 看现状

## 规则
- 不要重建整个蓝图（那是 create_new 的事）
- 一次只做用户明确要求的修改
- 改完后简短确认："已修改：删除 task X / 添加 task Y / ..."
- 改不了（项目已启动 / 任务 id 找不到）→ 坦诚告知，不要伪造成功"""


async def run(user_message: str, session: dict) -> SubAgentResult:
    session_id = session.get("id") or ""

    project_id = session.get("project_id")
    if not project_id:
        return empty_result(
            "没有可编辑的草稿蓝图（先用『新建项目』流程把草稿建出来）。"
        )

    try:
        provider, model_name = await resolve_session_llm_with_provider(session)
    except ValueError as exc:
        return empty_result(f"⚠️ LLM 配置错误：{exc}")

    # patch_blueprint tool — lazy import in case stage F isn't merged yet
    try:
        from src.tools.builtin.local.patch_blueprint import (
            make_patch_blueprint_tool,
        )
        patch_tool = make_patch_blueprint_tool(session_id)
    except ImportError:
        return empty_result(
            "蓝图微调工具尚未接入（patch_blueprint 待实现）。"
            "本次修改未生效；可以打开任务页直接编辑，或重启项目设计流程。"
        )

    from infra.repo import crud
    from src.tools.builtin.local.workspace import make_workspace_tools

    tools: list = [patch_tool]
    project = await crud.get_by_id("projects", project_id)
    root = project.get("root_path") if project else None
    if root:
        ws = make_workspace_tools(root)
        tools.extend([ws["read_file_local"], ws["list_directory_local"]])

    description = (
        f"## 用户请求\n{user_message}\n\n"
        "用 patch_blueprint 应用必要的 ops，然后一句中文确认改了什么。"
    )

    try:
        reply = await run_crewai_agent(
            session_id=session_id,
            role=_ROLE, goal=_GOAL, backstory=_BACKSTORY,
            description=description,
            expected_output="调 patch_blueprint 应用必要修改，然后一句中文确认。",
            tools=tools,
            provider=provider, model_name=model_name,
            max_iter=4,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("modify_blueprint.kickoff_failed", error=str(exc),
                  session_id=session_id)
        return empty_result(f"⚠️ 微调失败：{exc}")

    return {
        "reply_text": reply or "（无回复）",
        "project_id": project_id,
        "blueprint": None,
        "metadata": {"sub_agent": "modify_blueprint"},
    }
