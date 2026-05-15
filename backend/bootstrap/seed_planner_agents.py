"""Idempotent seeding of PM v3's auxiliary agents.

Currently seeds only one: 「项目初始化助手」(Project Initializer).
This agent is owned by Phase 4 of the v3 crew — every project gets a
kind="setup" task pre-assigned to it that runs `mkdir` for every
folder Phase 4 derived from the directory skeleton.

Singleton across projects (same agent_id reused) so it doesn't bloat
the agents table. Seeded with role/goal/backstory that explain its
narrow contract, plus a fixed minimal tool set.
"""
from __future__ import annotations

import json

import structlog

from infra.repo import crud

log = structlog.get_logger()


INITIALIZER_ROLE = "项目初始化助手"

_GOAL = (
    "在项目根目录下批量创建任务所需的所有子目录，确保后续业务任务"
    "写文件时父目录已就绪。"
)

_BACKSTORY = """你是 MyCrew 的项目初始化专员。座右铭：一次性建对所有目录，
不让下游 agent 因为父目录不存在挂掉。

# 你的工作
- 收到一个目录路径列表（项目根目录起算的相对路径）
- 依序调 `mkdir` 工具创建每一个目录（已存在的也调一次，mkdir 是幂等的）
- 全部建完后用 `list_directory_local` 抽样验证存在
- 调 `emit_output(payload={"file_paths": ["Assets/Scripts", ...]})` 报告所有建好的目录

# 严格约束
- 不写任何业务代码、不下载资产、不和其他 agent 协调
- 失败立即停（mkdir 返回错误 → 不要忽略 → 直接告知用户）
- 一次性把所有目录建完，不要分多轮 / 不要每个目录单独 emit
"""

_TOOL_NAMES = ["mkdir", "list_directory_local", "emit_output"]


async def ensure_project_initializer_agent(tool_name_to_id: dict[str, str]) -> str:
    """Insert the project initializer agent if missing. Returns its id.

    `tool_name_to_id` is the result of seed_builtin_tools.ensure_builtin_tools
    — passed in so we can resolve our tool names → tool_ids without
    re-querying the DB."""
    # Look for existing seeded agent (by role + is_auto_generated=0).
    existing = await crud.get_all(
        "agents",
        "role = ? AND is_auto_generated = 0",
        (INITIALIZER_ROLE,),
    )
    if existing:
        return existing[0]["id"]

    tool_ids = [tool_name_to_id[n] for n in _TOOL_NAMES if n in tool_name_to_id]

    # Resolve a default LLM — first configured provider+model. The agent's
    # work is mechanical so this is rarely a bottleneck; cheap_llm would
    # be ideal but the column may not be set, so just use any.
    providers = await crud.get_all("llm_providers")
    llm_id = ""
    if providers:
        first = providers[0]
        models = await crud.get_all("llm_models", "provider_id = ?", (first["id"],))
        if models:
            llm_id = f"{first['id']}:{models[0]['model_name']}"
        else:
            llm_id = first["id"]

    row = await crud.insert("agents", {
        "role": INITIALIZER_ROLE,
        "goal": _GOAL,
        "backstory": _BACKSTORY,
        "reasoning": 0,
        "max_retry": 2,
        "memory_enabled": 0,
        "memory_path": None,
        "thinking_mode": 0,
        "tool_ids": json.dumps(tool_ids),
        "llm_id": llm_id,
        "is_auto_generated": 0,
    }, id_prefix="agent_")
    log.info("seed.project_initializer_agent.created", id=row["id"])
    return row["id"]
