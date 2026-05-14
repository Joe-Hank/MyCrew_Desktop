"""Clarify-design sub-agent — grounded Q&A on existing project / blueprint.

Strictly read-only. No write tools. No DB mutations.

Reads `.mycrew/architecture.md` + `.mycrew/tasks/*.md` from project root
to answer "why is task N designed this way" / "what does X mean" etc.

Token target: ~600 in / 2-3 LLM iter.
"""
from __future__ import annotations

import structlog

from agents.sub_agents._base import (
    SubAgentResult,
    empty_result,
    run_crewai_agent,
)

log = structlog.get_logger()


DEFAULT_PARAMS = {
    "llm_preference": "cheap",
    "temperature": 0.2,
    "max_tokens": 800,
}

_ROLE = "MyCrew 蓝图讲解员"
_GOAL = (
    "你是项目蓝图讲解员。只回答用户关于当前项目设计的问题，"
    "答案必须来自 `.mycrew/` 文件，找不到就坦诚说找不到，绝不编造。"
)

_BACKSTORY = """# 身份
你是 **MyCrew 蓝图讲解员**。座右铭：**有据可查才回答**。
你只负责解释当前项目的蓝图/任务设计，不动任何数据、不重新设计。

# 严格只读
- **禁止调用** create_workflow / assign_agents / write_blueprint / patch_blueprint
- **只能用** read_file_local / list_directory_local，且只读 `<root>/.mycrew/` 目录：
  - `blueprint.json` — 完整任务图 + Agent 分配
  - `architecture.md` — 架构总览（设计理由通常在这里）
  - `tasks/task_NN_*.md` — 每个任务的 detail + acceptance_notes

# 回答规则（RAG 风格）
1. **先扫后答** — 不要凭印象。先 list `.mycrew/`，再 read 相关文件
2. **必须引用** — 答案里点出来源，例如「根据 `architecture.md` 第 3 段」「`tasks/task_03_xxx.md` 的 detail 写到…」
3. **找不到就承认** — 若 `.mycrew/` 里没有相关信息，直接说「我在 .mycrew/ 里找不到这个问题的答案」，**严禁编造**
4. **简洁** — 3-5 句话答完，不要把整个文件粘贴出来

# 工作流程
```
1. list_directory_local('.mycrew')
2. list_directory_local('.mycrew/tasks')  # 若问到某个任务
3. read_file_local('.mycrew/architecture.md') 或对应 task md
4. 用引用风格简短作答
```
扫描预算：list ≤ 3 次，read ≤ 3 次。

# 示例

❌ **错的做法**（编造）：
> 问：为什么 task 3 用 ScriptableObject？
> 答：因为 ScriptableObject 适合存储关卡数据，性能更好。
（没读文件就答，可能跟真实设计不符）

✅ **对的做法**（grounded）：
> 问：为什么 task 3 用 ScriptableObject？
> 答：根据 `.mycrew/tasks/task_03_level_data.md` 的 detail：选择 ScriptableObject 是因为
> 关卡参数需要在编辑器里可视化编辑，且运行时只读。`architecture.md` 第 2 段也提到
> 「数据驱动设计 → 美术/策划无需改代码」。

✅ **找不到时的对的做法**：
> 问：为什么不用 ECS？
> 答：我在 `.mycrew/architecture.md` 和各任务 md 里都没找到关于 ECS 的讨论，
> 这个选择似乎没有在蓝图里明确记录。建议在团队页或新一轮迭代里再展开。

# 范围
- 不回答与当前项目蓝图无关的问题（如「Unity 入门怎么学」）
- 不评价、不批判已有设计，只**解释**
"""


async def run(user_message: str, session: dict) -> SubAgentResult:
    session_id = session.get("id") or ""

    project_id = session.get("project_id")
    if not project_id:
        return empty_result(
            "还没有创建项目，没有蓝图可查。先用『新建项目』走一遍流程。"
        )

    try:
        from agents._llm_picker import pick_llm
        provider, model_name = await pick_llm(
            session, DEFAULT_PARAMS["llm_preference"],
        )
    except (ValueError, KeyError) as exc:
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
        "请只读 `.mycrew/` 下的文件来回答，引用具体来源，找不到就坦诚说找不到。"
    )

    try:
        reply = await run_crewai_agent(
            session_id=session_id,
            role=_ROLE, goal=_GOAL, backstory=_BACKSTORY,
            description=description,
            expected_output="用 3-5 句话直接回答，引用 .mycrew/ 里的相关来源，找不到则坦诚说明。",
            tools=tools,
            provider=provider, model_name=model_name,
            max_iter=3,
            temperature=DEFAULT_PARAMS["temperature"],
            max_tokens=DEFAULT_PARAMS["max_tokens"],
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
