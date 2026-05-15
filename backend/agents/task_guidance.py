"""Task-failure guidance chat — lightweight, single-turn LLM helper.

When a task fails or stalls, the user opens AgentChatDrawer on the task
card. This module answers their "why didn't this work?" questions.

Hard scope:
  - READ-ONLY: never modifies the task, never retries, never edits agent
  - Answers grounded in the task's in.md / out.md / detail / status /
    validation_errors — refuses to invent facts not in that context
  - Guides the user to manual action (edit task / click retry) rather
    than offering to do it itself
  - Stateless: each call gets the latest task snapshot; no chat history
    is persisted server-side
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud

log = structlog.get_logger()


DEFAULT_PARAMS = {
    "llm_preference": "cheap",
    "temperature": 0.3,
    "max_tokens": 800,
}


_SYSTEM_PROMPT = """你是 MyCrew 的**任务诊断助手**。座右铭：**解释原因 + 引导用户自助修复**。

# 你能做什么
- 看任务的输入（要求什么）、输出（实际产出，可能为空）、状态、验证错误，**解释为什么没完成**
- 用平实中文告诉用户**下一步在 UI 上怎么操作**（修改任务详情 / 改 agent / 改 output_schema / 点重试键）
- 如果信息不足以判断，**坦诚说"我看不出来"**，建议用户在哪查看日志

# 你不能做什么
- **不要假装能重启任务**。MyCrew 没给你这个权限，你只能用嘴指导
- **不要修改任务/agent/blueprint**。如果用户让你改，回复：
  "我只能解释，没法替你改。请在右上 ··· 菜单点【编辑任务】改完后点【重试】键。"
- **不要编造**任务/agent 的内部细节。只用上下文里给你的事实
- **不要执行代码 / 调工具**。你只有对话能力

# 回答风格
- 3-5 句话讲完，不要长篇大论
- 引用具体来源（"看输出里 validation_errors 第 1 条..."）
- 给一个明确的下一步动作
- 中文回答

# 示例

用户：为什么这个任务没跑完？
（上下文里 task.status=validation_failed, validation_errors=["missing field: file_path"]）
✓ 答："任务执行完了但输出校验没过。validation_errors 里写：缺少必填字段 `file_path`。
       Agent 没按 output_schema 把文件路径填进去——可能没真正写到磁盘，或写完没 emit_output 报告。
       建议：右上 ··· →【编辑任务】，在 detail 里补一句"完成后必须调 emit_output(file_path=...)"，
       然后点【重试】。"

用户：你能帮我重试吗？
✓ 答："我只能解释，没法替你点按钮。在任务卡片右上角 ··· 菜单里有【重试】键，
       或者改完任务详情后这个键会变可用。"
"""


def _read_text_safe(path_str: str | None, limit: int = 4000) -> str:
    if not path_str:
        return ""
    try:
        p = Path(path_str)
        if not p.exists():
            return ""
        return p.read_text(encoding="utf-8")[:limit]
    except OSError:
        return ""


def _read_sub_step_files(project_id: str, task_id: str, step_index: int) -> tuple[str, str]:
    """For Crew sub-step chat: return (in_text, out_text) from the
    `<OUTPUT_DIR>/<pid>/<tid>/sub/` folder. Either may be empty."""
    from bootstrap.paths import OUTPUT_DIR
    sub_dir = OUTPUT_DIR / (project_id or "") / task_id / "sub"
    if not sub_dir.exists():
        return "", ""
    in_text = ""
    out_text = ""
    for in_json in sub_dir.glob(f"{step_index}_*_in.json"):
        in_text = _read_text_safe(str(in_json))
        break
    # Prefer the markdown rendering of out for readability
    for out_md in sub_dir.glob(f"{step_index}_*_out.md"):
        out_text = _read_text_safe(str(out_md))
        break
    if not out_text:
        for out_json in sub_dir.glob(f"{step_index}_*_out.json"):
            out_text = _read_text_safe(str(out_json))
            break
    return in_text, out_text


async def _build_context(task: dict, step_index: int | None = None) -> str:
    """Render task facts into a Markdown block the LLM can ground on.

    When `step_index` is set the helper restricts the IO it reads to a
    single Crew step — keeps the conversation tightly scoped so the
    diagnostic doesn't drift between sibling steps' artifacts.
    """
    if step_index is not None:
        in_md, out_text = _read_sub_step_files(
            task.get("project_id", ""), task.get("id", ""), step_index,
        )
    else:
        in_md = _read_text_safe(task.get("io_in_ref"))
        out_md_path = task.get("io_out_ref")
        out_text = ""
        if out_md_path:
            p = Path(out_md_path)
            # io_out_ref points to out.json — read sibling out.md for raw text
            md_sibling = p.parent / "out.md"
            out_text = _read_text_safe(str(md_sibling)) or _read_text_safe(out_md_path)

    val_err = task.get("validation_errors")
    if val_err:
        import json
        if isinstance(val_err, str):
            try:
                val_err = json.loads(val_err)
            except (json.JSONDecodeError, TypeError):
                pass

    agent_role = ""
    agent_id = task.get("agent_id") or ""
    if agent_id:
        agent_row = await crud.get_by_id("agents", agent_id)
        if agent_row:
            agent_role = agent_row.get("role", "")

    parts = [
        "# 任务上下文",
        f"- **标题**: {task.get('title', '')}",
        f"- **状态**: `{task.get('status', '')}`",
        f"- **agent 角色**: {agent_role or '（未分配）'}",
        f"- **kind**: `{task.get('kind', 'regular')}`",
    ]
    if val_err:
        parts.append(f"- **validation_errors**: {val_err}")

    detail = (task.get("detail") or "").strip()
    if detail:
        parts.extend(["", "## 任务详细指令", detail[:1500]])

    if in_md:
        parts.extend(["", "## 任务输入（in.md）", "```", in_md[:1500], "```"])
    if out_text:
        parts.extend(["", "## 任务输出（out.md / raw）", "```", out_text[:1500], "```"])
    elif task.get("io_out_ref"):
        parts.append("\n（任务有 io_out_ref 但 raw 文本读不到，可能文件丢失）")
    else:
        parts.append("\n（任务还没产出任何输出）")

    return "\n".join(parts)


async def chat(
    task_id: str,
    user_message: str,
    session: dict | None = None,
    step_index: int | None = None,
    step_agent_id: str | None = None,
) -> dict[str, Any]:
    """Single-turn guidance chat for a task.

    Returns {"ok": bool, "reply": str, "error"?: str}.
    Stateless — no history persisted server-side; the chat drawer is
    expected to keep its own scrollback in component state.

    `step_index` (PM v4): when set, the helper scopes its grounding
    context to a single Crew step — reads sub/<i>_*_in/out.json instead
    of the parent task's in.md/out.md, and instructs the model to
    answer only about that step.
    """
    task = await crud.get_by_id("tasks", task_id)
    if not task:
        return {"ok": False, "error": "task_not_found",
                "reply": "找不到这个任务（可能已被删除）。"}

    # Pin the diagnostic agent to deepseek-flash. Rationale:
    #   - The user explicitly chose this LLM (2026-05-15) — task_guidance
    #     is a stateless single-turn Q&A, doesn't need to inherit the
    #     task's executing agent context, so it shouldn't be driven by
    #     pick_llm's fallback chain (which can land on whichever provider
    #     happens to be first in DB — landed Anthropic / blocked from
    #     CN in the 「霓虹攀升」 incident).
    #   - No fallback to other models if deepseek-flash isn't configured;
    #     log + return a clear error so the misconfig is visible.
    flash_models = await crud.get_all(
        "llm_models", "model_name LIKE ?", ("%deepseek%flash%",),
    )
    if not flash_models:
        log.warning("task_guidance.no_deepseek_flash")
        return {
            "ok": False, "error": "no_llm",
            "reply": "⚠️ 未配置 deepseek-flash 模型。请在设置页 LLM 列表里添加 "
                     "DeepSeek 提供方 + 一个 deepseek-*-flash 模型后再试。",
        }
    m = flash_models[0]
    provider = await crud.get_by_id("llm_providers", m["provider_id"])
    if provider is None:
        return {
            "ok": False, "error": "no_llm",
            "reply": "⚠️ deepseek-flash 模型记录指向的 provider 不存在。",
        }
    model_name = m["model_name"]

    context_md = await _build_context(task, step_index=step_index)

    # When the chat is scoped to a single Crew step, prepend a tight
    # instruction so the diagnostic stays focused on that step's IO
    # rather than the parent task as a whole.
    system_prompt = _SYSTEM_PROMPT
    if step_index is not None:
        scope_addendum = (
            f"\n\n# 本次会话的特殊限定\n"
            f"用户正在询问任务的第 {step_index + 1} 步（Crew 中的一步）。"
            f"上下文里只给了这一步的 in/out；**不要**讨论同 Crew 其他步骤的细节。"
        )
        if step_agent_id:
            scope_addendum += f" 这一步绑定的 agent id 是 `{step_agent_id}`。"
        system_prompt = _SYSTEM_PROMPT + scope_addendum

    messages = [
        LlmMessage(role="system", content=system_prompt),
        LlmMessage(role="user",
                   content=f"{context_md}\n\n---\n\n# 用户提问\n{user_message[:1000]}"),
    ]

    try:
        resp = await llm_gateway.chat(
            provider["id"], model_name, messages,
            max_tokens=DEFAULT_PARAMS["max_tokens"],
        )
    except Exception as exc:  # noqa: BLE001
        log.error("task_guidance.llm_failed", error=str(exc), task_id=task_id)
        return {"ok": False, "error": "llm_failed",
                "reply": f"⚠️ 诊断助手调用失败：{exc}"}

    return {"ok": True, "reply": (resp.text or "").strip() or "（无回复）"}
