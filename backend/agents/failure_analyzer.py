"""Failure analyzer — single-shot LLM diagnosis written to the task row
the moment it transitions to failed / validation_failed.

Why this exists
---------------
Pre-2026-05-17 the user had to open AgentChatDrawer and ask the
diagnostic agent ("为什么这个任务没跑完？") to read the same context
and produce the same explanation, every time. The chat back-and-forth
made sense when the answer might depend on what the user asked, but in
practice 95% of failures only need one canonical "原因 + 介入方法"
paragraph. Precomputing it once at failure time:

  - cuts a round-trip from "open drawer → type question → wait for LLM"
    to "click 失败原因 → read"
  - keeps the explanation pinned to the task row, so re-opening the
    project later still shows what the LLM concluded
  - frees the LLM-chat code path (task_guidance.py + AgentChatDrawer.tsx)
    to be re-enabled later via feature flag if interactive QA is still
    wanted

Trigger points (workflow_svc._run_one_task):
  - after `harness.validation_fail_task(...)` (schema/contract miss)
  - after `harness.fail_task(...)` (runtime exception / runner error)

Both call `asyncio.create_task(analyze_and_persist(...))` — fire and
forget; the user clicking the button before the LLM is done sees a
"分析中..." placeholder until the WS event lands.

Hard scope (same as task_guidance):
  - READ-ONLY; never retries, edits, or otherwise mutates execution
  - Grounded strictly in the task row + last_error + validation_errors
    + in.md / out.md / sub/<i>_*_out.* — no invented facts
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud

log = structlog.get_logger()


_SYSTEM_PROMPT = """你是 MyCrew 的**失败诊断助手**。每个任务一旦进入 failed 或 validation_failed 状态，你就被自动调用一次，给用户写一份精炼的"为什么失败 + 怎么介入"报告。

# 你看到的事实
- 任务标题 / 状态 / 执行者（Agent 或 Crew）
- last_error（运行时异常文本，可能为空）
- validation_errors（schema 校验错误列表，可能为空）
- 任务详细指令（PM 给的 detail）
- 输入上下文（in.md）+ 实际产出（out.md / 各 sub step 落盘文件）

# 输出格式（严格遵守，前端按这个结构渲染）

## 失败原因
（1-2 句精炼根因，引用具体证据。例："Crew 的 QA 步骤调 emit_output 时用了 `file_paths` 复数，但 task.output_schema 要求 `file_path` 单数 + required 这个键，所以校验拒绝。"）

## 证据
- 列 2-4 条事实，每条 1 行，引用具体来源（"validation_errors[0]: 'file_path' is a required property"、"sub/2_qa_out.json 里 payload 用的是 file_paths"）

## 怎么介入
1. **第一步**（最可能修好的动作，引导用户在 UI 上点哪里）
2. **第二步**（如果第一步不够，再做什么）
3. **如果还卡**（兜底建议，如打开日志 / 联系开发者）

# 风格硬约束
- 中文写，不超过 250 字
- 不要客套话（"你好"、"希望对你有帮助"）
- 不要重复任务标题
- 不要谈"未来防止再犯" —— 只解决眼前
- 不要建议"重新跑 PM 流程"除非真没别的路（重跑 PM 代价极高，能改 detail / 改 schema / 改 agent 就先改）
- 不要编造任务内部细节 —— 只用上下文里给你的事实；信息不够就明说"看不出来，请打开 ··· →【查看输入/输出】对照"

# 反面例子（不要这样写）
"任务遇到了一些问题。可能是 agent 配置的原因。建议你检查一下。" ← 空话 + 没证据 + 没动作

"任务标题：实现 HookController.cs。失败原因..." ← 重复标题浪费 token
"""


async def _gather_context(task: dict) -> str:
    """Reuse task_guidance._build_context for consistency. The two paths
    consume the same evidence; only the LLM instruction differs."""
    from agents.task_guidance import _build_context
    return await _build_context(task)


async def _pick_flash_model() -> tuple[str, str] | None:
    """Return (provider_id, model_name) for deepseek-flash, or None if
    not configured. Pinned to flash because diagnoses are short and the
    cost of a "couldn't analyze" message is lower than letting the
    fallback chain land on whichever provider is first in DB."""
    flash_models = await crud.get_all(
        "llm_models", "model_name LIKE ?", ("%deepseek%flash%",),
    )
    if not flash_models:
        log.warning("failure_analyzer.no_deepseek_flash")
        return None
    m = flash_models[0]
    provider = await crud.get_by_id("llm_providers", m["provider_id"])
    if provider is None:
        return None
    return provider["id"], m["model_name"]


async def analyze_and_persist(task_id: str) -> None:
    """The one entry point. Fire-and-forget; never raises out.

    Writes tasks.failure_analysis + .failure_analysis_at on success.
    On any failure (LLM down / no model / etc) writes a short
    placeholder so the UI doesn't spin forever — the user can still
    open the legacy AgentChatDrawer if it's re-enabled later.
    """
    try:
        task = await crud.get_by_id("tasks", task_id)
        if not task:
            log.warning("failure_analyzer.task_missing", task_id=task_id)
            return

        picked = await _pick_flash_model()
        if not picked:
            await _persist_placeholder(
                task_id,
                "⚠️ 未配置 deepseek-flash 模型，无法自动诊断。\n\n"
                "请在 设置页 → LLM 列表 添加 DeepSeek provider + 一个 "
                "*-flash 模型，然后重试任务（重试时会重新触发诊断）。",
            )
            return
        provider_id, model_name = picked

        context_md = await _gather_context(task)

        messages = [
            LlmMessage(role="system", content=_SYSTEM_PROMPT),
            LlmMessage(
                role="user",
                content=(
                    f"{context_md}\n\n---\n\n"
                    "# 请你按上方【输出格式】产出本次失败的诊断报告。"
                ),
            ),
        ]

        try:
            resp = await llm_gateway.chat(
                provider_id, model_name, messages, max_tokens=900,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("failure_analyzer.llm_failed",
                      task_id=task_id, error=str(exc))
            await _persist_placeholder(
                task_id,
                f"⚠️ 自动诊断调用失败：{exc}\n\n"
                "请打开任务的 ··· →【查看输入/输出】对照证据手动判断；"
                "如要回退到交互式诊断，可在设置中切回旧版 AgentChatDrawer。",
            )
            return

        text = (resp.text or "").strip() or "（诊断助手返回空回复）"
        await _persist_analysis(task_id, text)
        log.info("failure_analyzer.persisted",
                 task_id=task_id, chars=len(text))

        # WS broadcast so the open task card refreshes without polling.
        # The frontend invalidates the project query on this event.
        try:
            from infra.ws import manager
            await manager.broadcast("task.failure_analyzed", {
                "task_id": task_id,
                "project_id": task.get("project_id"),
                "ts": _now_iso(),
            })
        except Exception as exc:  # noqa: BLE001 — WS issues must not break persist
            log.warning("failure_analyzer.ws_broadcast_failed",
                        task_id=task_id, error=str(exc))

    except Exception as exc:  # noqa: BLE001 — outermost guard, fire-and-forget
        log.error("failure_analyzer.unhandled",
                  task_id=task_id, error=str(exc))


async def _persist_analysis(task_id: str, text: str) -> None:
    await crud.update_by_id("tasks", task_id, {
        "failure_analysis": text,
        "failure_analysis_at": _now_iso(),
    })


async def _persist_placeholder(task_id: str, text: str) -> None:
    """Same shape as success but with a visible warning prefix so the
    UI can tell"computed" from "couldn't compute" later if needed.
    Today both render the same way; the prefix is human-readable."""
    await _persist_analysis(task_id, text)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def spawn(task_id: str) -> asyncio.Task[None]:
    """Fire-and-forget spawn. Returns the task so callers can store it
    if they care about lifecycle (workflow_svc does not). Errors are
    swallowed inside analyze_and_persist; the returned Task never
    raises on await."""
    return asyncio.create_task(analyze_and_persist(task_id))


__all__ = ["analyze_and_persist", "spawn"]
