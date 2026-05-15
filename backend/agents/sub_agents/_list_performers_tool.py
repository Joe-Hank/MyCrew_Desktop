"""PM v4 Phase 5 — list_performers tool.

Grill Q8 decision: instead of dumping the full performer pool into the
Phase 5 backstory (long prompt, easy to hallucinate ids past the cache
window), expose it as a tool the LLM must call. The args_schema in
submit_assignments then strictly requires PerformerRef.id; ids that
were never in the tool output get rejected by Pydantic before they
reach the orchestrator.

The tool is read-only and side-effect-free — it just queries the
agents + crews tables and returns a deterministic JSON snapshot.

NOT used by Phase 2/3 (Q8): those phases get a static, more compact
summary embedded in their backstory; they don't need the full
id-to-scenario map because they're not choosing performers.
"""
from __future__ import annotations

import json
from typing import ClassVar, Literal

import structlog
from pydantic import BaseModel, Field

from infra.repo import crud
from src.tools.builtin._base import GuardedLocalTool

log = structlog.get_logger()


# ── Filtering ─────────────────────────────────────────────────────
#
# Phase 5 should not see:
#   - Plan Maker (orchestration role, not an executor)
#   - 项目初始化助手 (already pre-assigned to setup task by Phase 4)
#   - Crew-internal-only agents that never appear standalone — these are
#     the bulk of SEED_AGENTS (Concept Artist, ComfyUI Image Generator,
#     Technical Artist, …). They participate inside Crews; standalone
#     they would be missing the head/QA scaffolding the Crew provides.
#
# Standalone-eligible single agents per the plan: 项目初始化助手 (excluded
# above), Narrative Designer, Level Designer, System Designer, Art Director.

_STANDALONE_AGENT_ROLES = {
    "Narrative Designer",
    "Level Designer",
    "System Designer",
    "Art Director",
}

_EXCLUDED_ROLES = {
    "Plan Maker",
    "项目初始化助手",
}


# ── Args ──────────────────────────────────────────────────────────


class ListPerformersArgs(BaseModel):
    kind: Literal["all", "agent", "crew"] = Field(
        "all",
        description="过滤池子；'all' 返回 agent 和 crew，'agent' 仅 agent，'crew' 仅 crew。",
    )


# ── Tool ──────────────────────────────────────────────────────────


class ListPerformers(GuardedLocalTool):
    name: str = "list_performers"
    description: str = (
        "列出可选 performer（agent / Crew）池。返回每个 performer 的 "
        "id、kind、role/name、applicable_scenarios 描述。**Phase 5 只能从"
        "本工具返回的池子里选**：submit_assignments 的 performer_ref.id "
        "必须是这里出现过的 id；编造或猜测的 id 会被 Pydantic 拒绝。"
    )
    args_schema: type[BaseModel] = ListPerformersArgs
    permission_kind: ClassVar[str | None] = None

    def _run(self, kind: str = "all") -> str:
        async def _do() -> str:
            payload = await _build_payload(kind)
            return json.dumps(payload, ensure_ascii=False, indent=2)
        try:
            return self._guarded_local(_do)
        except Exception as exc:  # noqa: BLE001
            log.error("list_performers.failed", error=str(exc))
            return f"[Error] list_performers failed: {exc}"


async def _build_payload(kind: str) -> dict:
    """Pull the standalone agents + crews. Returns a stable JSON shape."""
    agents_out: list[dict] = []
    if kind in ("all", "agent"):
        rows = await crud.get_all("agents")
        for r in rows:
            role = r.get("role", "")
            if role in _EXCLUDED_ROLES:
                continue
            if role not in _STANDALONE_AGENT_ROLES:
                continue
            agents_out.append({
                "kind": "agent",
                "id": r["id"],
                "role": role,
                "goal": (r.get("goal") or "").split("\n")[0][:120],
                "applicable_scenarios": _scenario_for_agent(role),
            })

    crews_out: list[dict] = []
    if kind in ("all", "crew"):
        rows = await crud.get_all("crews")
        # Filter client-side so the FakeCRUD test harness (which only
        # parses "col = ?" where-clauses) matches production behavior.
        rows = [r for r in rows if not r.get("is_auto_generated")]
        for r in rows:
            crews_out.append({
                "kind": "crew",
                "id": r["id"],
                "name": r.get("name", ""),
                "applicable_scenarios": r.get("applicable_scenarios", ""),
                "step_count": _step_count(r),
            })

    return {
        "summary": (
            f"{len(agents_out)} agent(s) + {len(crews_out)} Crew(s) available. "
            "提交 submit_assignments 时 performer_ref.id 只能用本列表里的 id。"
        ),
        "agents": agents_out,
        "crews": crews_out,
    }


def _scenario_for_agent(role: str) -> str:
    """Hand-curated one-line scenario hint for the standalone agents."""
    return {
        "Narrative Designer": "纯文档输出：叙事 / 文案 / 剧情设计文档",
        "Level Designer": "关卡设计文档（不实装场景；要实装走 Scene Assembly Crew）",
        "System Designer": "系统设计文档（不实装代码；要实装走 System Implementation Crew）",
        "Art Director": "美术风格指南文档（不实际产资产；要产资产走 Art / 3D Asset / Animation / VFX Crew）",
    }.get(role, "")


def _step_count(crew_row: dict) -> int:
    seq_raw = crew_row.get("agent_sequence") or "[]"
    try:
        seq = json.loads(seq_raw) if isinstance(seq_raw, str) else seq_raw
        return len(seq) if isinstance(seq, list) else 0
    except (json.JSONDecodeError, TypeError):
        return 0


def make_list_performers_tool() -> ListPerformers:
    return ListPerformers()


# ── Helper used by Phase 2/3 backstory rendering (static summary) ──

async def render_performer_pool_static_summary() -> str:
    """Return a compact human-readable summary of the pool — for embedding
    in Phase 2/3 backstories so they know the executor granularity.

    Phase 2/3 don't pick performers; they just need awareness of what
    sized chunks the executors can chew at. Keeping this brief keeps the
    prompt small."""
    payload = await _build_payload("all")
    lines: list[str] = []
    if payload["agents"]:
        lines.append("## 可用单 Agent（轻量、单步任务）")
        for a in payload["agents"]:
            lines.append(f"- {a['role']} — {a['applicable_scenarios']}")
    if payload["crews"]:
        lines.append("")
        lines.append("## 可用 Crew（多步协作，自带 QA 子步骤）")
        for c in payload["crews"]:
            lines.append(f"- {c['name']} — {c['applicable_scenarios']}")
    return "\n".join(lines) or "（performer 池为空）"


__all__ = [
    "ListPerformers",
    "ListPerformersArgs",
    "make_list_performers_tool",
    "render_performer_pool_static_summary",
]
