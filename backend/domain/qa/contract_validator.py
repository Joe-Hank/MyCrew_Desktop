"""V5 Stage B — verify generated .cs files match the PM-issued code contract.

Phase 5 (PM v5) writes a `tasks.code_contract` row listing the public
classes / methods / events / fields each .cs file MUST contain. After a
task's Crew finishes and emit_output passes the JSON-schema check, the
workflow runner calls this module to verify the actual files on disk
contain every contracted signature. Missing → task moves to
validation_failed with a concrete "缺少签名 X" message so the user
knows exactly what the Crew skipped.

Algorithm (v5 MVP — decision Q4):
  1. Read the .cs file.
  2. Normalize: strip C-style comments + collapse all whitespace
     (including newlines) to single spaces. This handles Crews that
     emit multi-line method headers and varied indentation.
  3. For each contract signature, normalize the same way and do a
     substring-match against the normalized file.

Why substring-match instead of an AST parser:
  - PM Phase 5 prompts already forbid multi-line signatures / nested
    generics > 2 levels / partial class. The signature strings are
    therefore well-formed C# tokens that uniquely identify a member.
  - Pulling in Roslyn (needs .NET runtime + cross-platform helper exe)
    is V6+ territory; substring on normalized text covers ~95% of the
    cases this V5 cut needs to catch.
  - Compiler-level "does it actually build" is covered by the Unity
    console layer (manage_editor refresh + read_console), which Crew
    QA steps already invoke. Contract verification + compile check
    together = belt + suspenders.

False positives we accept:
  - A signature string buried inside a string literal would match (no
    real C# parser, can't tell code from string). Crew won't write
    such code in practice.
False negatives we accept:
  - A class generated via `partial class` won't match a non-partial
    contract signature. Same constraint already documented in the
    Phase 5 prompt.
"""
from __future__ import annotations

import re
from pathlib import Path

import structlog

log = structlog.get_logger()


# Strip // line comments and /* block */ comments. DOTALL lets the
# block comment span newlines.
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
# Any run of whitespace (incl. newlines) → single space.
_WS_RE = re.compile(r"\s+")
# Strip ANY whitespace adjacent to these punctuation tokens. Without
# this, the contract signature `Move(Vector2 d, float s)` doesn't
# substring-match a multi-line file's `Move( Vector2 d,\n  float s)`
# even after the basic whitespace-collapse — because the file has a
# space after `(` and after `,` that the contract doesn't. Normalising
# both sides to "no space around these" makes the comparison robust.
_PUNCT_SPACE_RE = re.compile(r"\s*([(),;<>])\s*")


def normalize_csharp(text: str) -> str:
    """Strip comments, collapse whitespace, tighten punctuation spacing.
    Lowercase is NOT applied — C# is case-sensitive, contract signatures
    must match in case."""
    text = _COMMENT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    text = _PUNCT_SPACE_RE.sub(r"\1", text)
    return text.strip()


def verify_contract(
    contract: dict,
    project_root: Path,
) -> list[str]:
    """Walk every contract.files[i].exports[j] and confirm the listed
    signature appears (whitespace-normalized) inside the .cs file at
    contract.files[i].path. Returns a flat list of human-readable
    error strings; empty list = full contract honoured.

    `contract` is the dict shape produced by Phase 5's
    submit_code_contracts tool. `project_root` is the absolute path on
    disk where output_paths are anchored (project.root_path).
    """
    errors: list[str] = []
    files = contract.get("files") or []
    if not files:
        # An empty contract.files is a Phase-5 bug, but at validation
        # time treat it as "nothing to check" rather than failing the
        # generated code (the upstream phase validator already caught it).
        return errors

    for f in files:
        path_str = f.get("path") or ""
        if not path_str:
            errors.append("contract.files[].path 为空 — PM 输出有缺")
            continue
        abs_path = (
            Path(path_str) if Path(path_str).is_absolute()
            else project_root / path_str
        )
        if not abs_path.exists():
            errors.append(
                f"{path_str}: 文件不存在 — Crew Executor 没产出该 .cs"
            )
            continue
        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{path_str}: 读取失败 ({exc})")
            continue

        normalized_file = normalize_csharp(content)
        exports = f.get("exports") or []
        missing_in_file: list[str] = []
        for exp in exports:
            sig = (exp.get("signature") or "").strip()
            if not sig:
                continue
            normalized_sig = normalize_csharp(sig)
            if not normalized_sig:
                continue
            if normalized_sig not in normalized_file:
                kind = exp.get("kind") or "?"
                missing_in_file.append(f"({kind}) `{sig}`")

        if missing_in_file:
            # One error string per file so the message stays readable
            # even when many signatures are missing.
            joined = "; ".join(missing_in_file[:6])
            more = (
                f"（还有 {len(missing_in_file) - 6} 项）"
                if len(missing_in_file) > 6 else ""
            )
            errors.append(
                f"{path_str}: 缺少契约签名 — {joined}{more}"
            )

    if errors:
        log.info("contract_validator.failed",
                 file_count=len(files), error_count=len(errors))
    return errors


__all__ = ["normalize_csharp", "verify_contract"]
