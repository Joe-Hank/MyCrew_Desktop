"""VerifyOutputs — Layer 2 of the 2026-05-21 architecture refactor.

What this tool does
-------------------
Confirms that the files the agent claims to have produced actually
exist on disk under the project root. Returns "OK" on success, or a
specific list of missing files on failure.

Why this tool exists
--------------------
Layer 1 (Task(output_pydantic=Spec)) lets CrewAI 1.14's Converter
enforce schema shape — Probe 1 (2026-05-21) showed Qwen-plus produces
valid ExecutorOutput in 10/10 trials. But schema shape is NOT enough:
an agent can declare `file_paths=["Assets/Foo.cs"]` without ever
calling `create_script`. Empirically observed in fruit-ninja
(task_208e6857bf1f executor: file_paths claim but no actual files).

`verify_outputs` plugs that hole IN THE AGENT LOOP — the agent calls
this tool before terminating, gets back "missing X.cs", then can call
`write_file` / `create_script` to actually produce the files and
retry. This is the self-correction property the Plan agent's review
flagged as irreplaceable: framework Converter retries have no tool
access (single-shot text→Pydantic coercion), so disk verification
must happen via a tool while the agent is still running.

Bound at instantiation
----------------------
`project_root` and the PM-declared `expected_paths` are bound via the
factory — the LLM sees only `file_paths` in the signature, can't spoof
the root, can't drop entries from the PM contract.

Forced via tool_choice
----------------------
Probe 2 (2026-05-21) verified: on Qwen,
`tool_choice={"type": "function", "function": {"name": "verify_outputs"}}`
forces the call 5/5 trials. `tool_choice="required"` is NOT enough —
it lets the model pick any tool (5/5 picked list_directory). Layer 2
must use the specific-function form. crewai_runner wires this when
the step has output_pydantic and the provider supports it.
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import structlog
from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedLocalTool

log = structlog.get_logger()


class VerifyOutputsArgs(BaseModel):
    file_paths: list[str] = Field(
        ...,
        description=(
            "The files this step has produced (relative to project root). "
            "Pass exactly the list you intend to declare in your final "
            "output — this tool will reject the call if any of them are "
            "missing on disk, so use it as your last self-check."
        ),
    )


class VerifyOutputs(GuardedLocalTool):
    name: str = "verify_outputs"
    description: str = (
        "Before finishing this step, call verify_outputs(file_paths=[...]) "
        "to confirm every file you claim to have produced is actually on "
        "disk. Returns 'OK' on success, or a list of missing paths so you "
        "can call write_file / create_script to fix and retry. "
        "Use this exactly once, near the end of your work."
    )
    args_schema: type[BaseModel] = VerifyOutputsArgs
    # No side-effects on filesystem / network — pure read check.
    permission_kind: ClassVar[str | None] = None

    _bound_root: ClassVar[str] = ""
    # PM contract — task.output_paths the agent MUST cover. Cross-checked
    # against the agent's declared file_paths so an agent can't drop
    # contracted files just because it didn't make them.
    _bound_expected_paths: ClassVar[tuple[str, ...]] = ()

    def _run(self, file_paths: list[str]) -> str:
        if not isinstance(file_paths, list):
            return (
                "[ValidationError] file_paths must be a list of strings "
                f"(got {type(file_paths).__name__})."
            )

        # Normalise: strip whitespace, drop empties, dedupe preserving order.
        seen: set[str] = set()
        clean: list[str] = []
        for p in file_paths:
            if not isinstance(p, str):
                continue
            s = p.strip()
            if not s or s in seen:
                continue
            seen.add(s)
            clean.append(s)

        # Cross-check against PM contract: every expected path MUST appear
        # in the agent's declared list. Catches "agent quietly dropped
        # contracted files" — a separate failure mode from "files don't
        # exist on disk".
        if self._bound_expected_paths:
            missing_from_decl = [
                p for p in self._bound_expected_paths if p not in seen
            ]
            if missing_from_decl:
                listed = ", ".join(missing_from_decl[:6])
                more = (
                    f" (and {len(missing_from_decl) - 6} more)"
                    if len(missing_from_decl) > 6 else ""
                )
                return (
                    "[ValidationError] task.output_paths declares files "
                    f"you did not include in your verify_outputs list: "
                    f"{listed}{more}. Add them to file_paths and try again "
                    "— PM contract requires every entry to be produced."
                )

        if not self._bound_root:
            # Probe / unbound — just report the agent's list back. Not
            # production-realistic but useful for unit tests.
            return f"OK (no project_root bound — declared {len(clean)} files: {clean})"

        root_p = Path(self._bound_root)
        missing_on_disk: list[str] = []
        zero_byte: list[str] = []
        for rel in clean:
            p = Path(rel)
            absolute = p if p.is_absolute() else (root_p / p)
            try:
                if not absolute.exists():
                    missing_on_disk.append(rel)
                    continue
                # A 0-byte file is almost always a failed write or a
                # placeholder — surface separately so the agent doesn't
                # think it's done.
                if absolute.is_file() and absolute.stat().st_size == 0:
                    zero_byte.append(rel)
            except (OSError, PermissionError):
                missing_on_disk.append(rel)

        issues: list[str] = []
        if missing_on_disk:
            listed = ", ".join(missing_on_disk[:6])
            more = (
                f" (and {len(missing_on_disk) - 6} more)"
                if len(missing_on_disk) > 6 else ""
            )
            issues.append(
                f"missing on disk: {listed}{more}. Use write_file / "
                f"create_script to create them, then call verify_outputs again."
            )
        if zero_byte:
            listed = ", ".join(zero_byte[:6])
            more = (
                f" (and {len(zero_byte) - 6} more)"
                if len(zero_byte) > 6 else ""
            )
            issues.append(
                f"zero-byte files (likely failed writes): {listed}{more}. "
                f"Open each, write real content, then call verify_outputs again."
            )

        if issues:
            return "[ValidationError] " + " | ".join(issues)

        log.info("verify_outputs.passed",
                 declared=len(clean), root=self._bound_root)
        return f"OK — verified {len(clean)} file(s) exist and are non-empty."


def make_verify_outputs_tool(*, project_root: str = "",
                              expected_paths: list[str] | None = None) -> VerifyOutputs:
    """Factory binding the per-task project_root + PM contract.

    Mirrors make_emit_output_tool's pattern: the LLM sees only
    `file_paths` in the function signature; root + expected list are
    closure-bound class attributes so the model can't spoof them.

    ``expected_paths`` defaults to None → no contract cross-check.
    For typical Crew steps, pass `task.output_paths` so the tool
    catches "agent dropped contracted files".
    """
    expected = tuple(expected_paths or ())

    class _Bound(VerifyOutputs):
        _bound_root: ClassVar[str] = project_root or ""
        _bound_expected_paths: ClassVar[tuple[str, ...]] = expected

    return _Bound()


__all__ = ["VerifyOutputs", "make_verify_outputs_tool"]
