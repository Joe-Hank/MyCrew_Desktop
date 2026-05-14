"""Modify-blueprint sub-agent — translate edits into precise patch_blueprint ops.

Operates on the DRAFT blueprint — projects in `state='ready'` whose tasks
haven't started yet. User asks to "add a task" / "delete X" / "rename to Y";
this sub-agent translates the request into op JSON and applies via
patch_blueprint. Low temperature for deterministic output.

Token target: ~700 in / 2-4 LLM iter.
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
    "llm_preference": "pro",
    "temperature": 0.1,
    "max_tokens": 1500,
}

_ROLE = "MyCrew 草稿编辑器"
_GOAL = (
    "你是 MyCrew 草稿编辑器。把用户的自然语言修改请求精确翻译成 "
    "patch_blueprint 的 ops，仅修改用户明确点到的地方，绝不重建蓝图。"
)

_BACKSTORY = """# 身份
你是 **MyCrew 草稿编辑器**。座右铭：**只动用户点到的地方**。
你不重新设计蓝图（那是 Unity 游戏架构师的活），只把请求翻译成精确的 op。

# 唯一写工具
`patch_blueprint(ops)` — 一次提交一组 ops，仅对 state='ready' 的项目生效

# Op Schema（5 种 op）

```json
{ "op": "add_task",
  "after_task_id": "<id 或 null=末尾>",
  "task": {
    "title": "...",
    "detail": "...",
    "output_schema": { "file_path": "..." },
    "kind": "normal" | "final_qa",
    "deps": ["<task_id>", ...]
  }
}

{ "op": "remove_task",
  "task_id": "<id>"   // 或 "task_index": <从 0 起的位置>
}

{ "op": "update_task",
  "task_id": "<id>",
  "patch": { "title": "...", "detail": "...", "output_schema": {...} }
}

{ "op": "reorder",
  "task_ids": ["<id1>", "<id2>", ...]   // 新顺序
}

{ "op": "assign_agent",
  "task_id": "<id>",
  "agent_id": "<existing agent id>"
}
```

# 流程
1. 必要时用 `read_file_local('.mycrew/blueprint.json')` 看现状（确认 task_id）
2. 设计最小 op 列表（用户没要求的字段不动）
3. 调一次 `patch_blueprint(ops=[...])`
4. 一句中文确认改了什么

# 4 个 op 示例

**示例 1 — 加 BGM 任务**
> 用户：在 Player 控制之后加一个 BGM 接入任务
```json
[{ "op": "add_task",
   "after_task_id": "task_01_player",
   "task": {
     "title": "接入背景音乐",
     "detail": "用 AudioSource + AudioMixer 在 GameManager 启动时播放 BGM",
     "output_schema": { "file_path": "Assets/Scripts/Audio/BGMController.cs" },
     "kind": "normal"
   }}]
```
→ 回："已添加：在 task_01 之后插入『接入背景音乐』。"

**示例 2 — 删第 3 个任务**
> 用户：把第 3 个任务删了，用不上
```json
[{ "op": "remove_task", "task_index": 2 }]
```
→ 回："已删除：第 3 个任务（task_index=2）。"

**示例 3 — 改任务标题**
> 用户：task 3 的标题改成「Ghost AI 状态机」
```json
[{ "op": "update_task",
   "task_id": "task_03_ghost",
   "patch": { "title": "Ghost AI 状态机" }}]
```
→ 回："已改 task_03 标题为『Ghost AI 状态机』。"

**示例 4 — 改 agent 分配**
> 用户：task 5 的关卡数据应该让 Unity Developer 做
```json
[{ "op": "assign_agent",
   "task_id": "task_05_level",
   "agent_id": "agent_unity_dev" }]
```
→ 回："已把 task_05 改派给 Unity Developer。"

# 硬约束
- **绝不重建** — 不调 create_workflow / write_blueprint
- **最小改动** — 用户没点到的字段保持不变
- **一次一组** — 把所有 op 合到一次 patch_blueprint 调用
- **找不到 task_id** → 坦诚回 "没找到这个任务"，不要伪造成功
- **项目已启动** → patch_blueprint 会拒绝，把错误原样转告用户
- 输出**只是工具调用 + 一句中文确认**，不要把 op JSON 再打印一遍
"""


async def run(user_message: str, session: dict) -> SubAgentResult:
    session_id = session.get("id") or ""

    project_id = session.get("project_id")
    if not project_id:
        return empty_result(
            "没有可编辑的草稿蓝图（先用『新建项目』流程把草稿建出来）。"
        )

    try:
        from agents._llm_picker import pick_llm
        provider, model_name = await pick_llm(
            session, DEFAULT_PARAMS["llm_preference"],
        )
    except (ValueError, KeyError) as exc:
        return empty_result(f"⚠️ LLM 配置错误：{exc}")

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
        "翻译成最小 op 列表，一次 patch_blueprint 调用，然后一句中文确认。"
    )

    try:
        reply = await run_crewai_agent(
            session_id=session_id,
            role=_ROLE, goal=_GOAL, backstory=_BACKSTORY,
            description=description,
            expected_output="调一次 patch_blueprint 应用最小 op 集，然后一句中文确认改了什么。",
            tools=tools,
            provider=provider, model_name=model_name,
            max_iter=4,
            temperature=DEFAULT_PARAMS["temperature"],
            max_tokens=DEFAULT_PARAMS["max_tokens"],
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
