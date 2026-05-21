"""Pydantic Specs for Crew step outputs (Layer 1 of the 2026-05-21 refactor).

Background
----------
Until this refactor, every Crew step's output was a free-form `dict`
captured by the `emit_output` tool. Experimental data (N=5 × 5 provider
combinations, fruit-ninja project, 2026-05-21) showed `emit_output`'s
self-fire rate is 0/5 across every configuration — the architecture has
been kept alive by 4 rescue branches in workflow_svc.

This module replaces the "agent must remember to call emit_output with
the right shape" contract with framework-enforced typed outputs:

  - Each Crew step declares its output type as a `BaseModel` subclass.
  - `Task(output_pydantic=<Spec>)` lets CrewAI 1.14's Converter run the
    LLM in structured-output mode (Probe 1 on Qwen-plus: 10/10 pydantic OK).
  - workflow_svc reads `task.output.pydantic.model_dump()` directly
    instead of relying on `pop_output(task_id)` from the rescue layer.

Per-Crew variants live here so seed_crews can wire them at step level.
The existing PM-side `_planner_models.py` follows the same convention —
this file mirrors that pattern for Crew (runtime) steps.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────
# Common bases — reused across Crews.
# ──────────────────────────────────────────────────────────────────────


class HeadSpec(BaseModel):
    """Generic Head-step output: a spec describing what the Executor
    should produce. Mostly text-driven, with optional structured
    pointers. Used by System Designer / UI/UX Designer / Audio Designer
    / VFX Artist / etc. when their job is "spec, don't build".

    The `file_paths` field is the **intended** output set — the
    Executor will produce these. It MUST match the PM-declared
    task.output_paths; we validate that match in workflow_svc.
    """
    file_paths: list[str] = Field(
        default_factory=list,
        description="Files the Executor is expected to produce (mirrors task.output_paths).",
    )
    spec_markdown: str = Field(
        ...,
        description=(
            "Detailed implementation spec in markdown. Method signatures, "
            "state machines, algorithm steps, etc. Executor reads this verbatim."
        ),
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Optional auxiliary notes (dependencies, assumptions, risks).",
    )


class ExecutorOutput(BaseModel):
    """Generic Executor-step output: files produced + coverage report.

    Used for code-producing Crews (System Implementation / UI
    Implementation / Audio Implementation / VFX). Image / 3D Crews
    have their own variants below.
    """
    file_paths: list[str] = Field(
        ...,
        description="Paths of files produced, relative to project root.",
    )
    coverage: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Per-file count of contract signatures (or features) implemented. "
            "Used by QA to verify completeness."
        ),
    )
    summary: str = Field(
        default="",
        description="One- or two-line summary of what was done.",
    )


class QAOutput(BaseModel):
    """Generic QA-step output: verdict + evidence.

    Used by every QA Engineer step. The verdict field is the gate
    workflow_svc reads via `_collect_verdict_errors` — fail surfaces
    as task error in the harness.
    """
    verdict: Literal["pass", "fail"] = Field(
        ...,
        description=(
            "'pass' iff every contract check passed; 'fail' otherwise. "
            "Use 'fail' liberally — silent passes hide bugs in production."
        ),
    )
    file_paths: list[str] = Field(
        ...,
        description="Files that were verified (mirrors task.output_paths).",
    )
    issues: list[str] = Field(
        default_factory=list,
        description=(
            "Specific issues found, one per line. Required when verdict='fail'. "
            "Include enough detail for Debugger / human to locate the problem."
        ),
    )
    summary: str = Field(
        default="",
        description="One-line summary for the canvas tooltip and failure_analyzer.",
    )


# ──────────────────────────────────────────────────────────────────────
# Crew-specific variants — extend the bases where a Crew needs more.
# ──────────────────────────────────────────────────────────────────────


class ImageExecutorOutput(ExecutorOutput):
    """Art Crew / UI Crew Executor: image generation produces files with
    contracted dimensions. width / height are required so QA can verify
    against task.output_schema instead of trusting the agent's claim."""
    width: int = Field(..., description="Actual width of produced PNG (px).")
    height: int = Field(..., description="Actual height of produced PNG (px).")


class ImageQAOutput(QAOutput):
    """Art Crew / UI Crew QA: width / height carried through for downstream
    consumers (Unity import config, layout calculation)."""
    width: int = Field(..., description="Verified PNG width (px).")
    height: int = Field(..., description="Verified PNG height (px).")


class PromptSmithOutput(BaseModel):
    """Art Crew Head (PromptSmith): per-image subject prompt map.

    Output shape: `{prompts: {<output_path>: {subject_prompt, seed}}}`.
    Style prompt comes from project-level art_style_spec, not here.
    """
    class _SubjectEntry(BaseModel):
        subject_prompt: str = Field(..., description="Single-subject description, 10-30 tokens.")
        seed: int = Field(default=12345, description="Deterministic seed for this image.")

    prompts: dict[str, _SubjectEntry] = Field(
        ...,
        description="Map from output_path → subject prompt + seed.",
    )


# ──────────────────────────────────────────────────────────────────────
# Resolution registry — seed_crews / crewai_runner uses this to find
# the right Spec class for (crew_name, step_role).
# ──────────────────────────────────────────────────────────────────────


SPEC_REGISTRY: dict[tuple[str, str], type[BaseModel]] = {
    # System Implementation Crew — first migration target.
    ("系统实现组", "head"):     HeadSpec,
    ("系统实现组", "executor"): ExecutorOutput,
    ("系统实现组", "qa"):       QAOutput,
    # UI Implementation Crew — same shape as system_impl (code + assembly).
    ("UI 实现组", "head"):      HeadSpec,
    ("UI 实现组", "executor"):  ExecutorOutput,
    ("UI 实现组", "qa"):        QAOutput,
    # Audio / VFX / Scene Assembly use the generic shapes too.
    ("音频实现组", "head"):     HeadSpec,
    ("音频实现组", "executor"): ExecutorOutput,
    ("音频实现组", "qa"):       QAOutput,
    ("VFX 实现组", "head"):     HeadSpec,
    ("VFX 实现组", "executor"): ExecutorOutput,
    ("VFX 实现组", "qa"):       QAOutput,
    ("场景组装组", "head"):     HeadSpec,
    ("场景组装组", "executor"): ExecutorOutput,
    ("场景组装组", "qa"):       QAOutput,
    # Art Crew has the image-specific variants.
    ("美术资产组", "head"):     PromptSmithOutput,
    ("美术资产组", "executor"): ImageExecutorOutput,
    ("美术资产组", "qa"):       ImageQAOutput,
}


def spec_for(crew_name: str, step_role: str) -> type[BaseModel] | None:
    """Return the Pydantic Spec class for a (crew_name, step_role), or
    None when no Spec is registered yet — caller falls back to the
    legacy `emit_output` dict path. Used during gradual migration so
    Crews not yet covered keep working unchanged."""
    return SPEC_REGISTRY.get((crew_name, step_role))


__all__ = [
    "HeadSpec",
    "ExecutorOutput",
    "QAOutput",
    "ImageExecutorOutput",
    "ImageQAOutput",
    "PromptSmithOutput",
    "SPEC_REGISTRY",
    "spec_for",
]
