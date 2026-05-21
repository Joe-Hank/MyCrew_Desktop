"""Workflow service — start/pause/resume Harness; state changes persisted each step."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from domain.harness.states import ProjectState, TaskState
from domain.harness.state_machine import HarnessStateMachine
from domain.harness.task_runner import TaskRunner, TaskInput, TaskOutput
from domain.qa.dag_validator import validate_dag
from domain.qa.output_validator import validate_output_schema
from domain.events import DomainEvent
from infra.llm.base import LlmMessage
from infra.llm.gateway import llm_gateway
from infra.repo import crud
from infra.event_bus.in_memory_bus import event_bus

log = structlog.get_logger()


# ── Failure classification ─────────────────────────────────────────
# Heuristics on the exception string. Generic but enough to give the
# user a one-word hint on hover instead of just "执行失败".
# Order matters — most specific patterns first.
_ERROR_KIND_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("quota", (
        "rate_limit", "rate limit", "ratelimit", "quota", "insufficient_quota",
        "billing", "exceeded your current quota", "tokens_exhausted",
        "402", "payment required", "余额不足", "额度",
    )),
    ("auth", (
        "401", "unauthorized", "invalid api key", "incorrect api key",
        "authentication", "auth_failed",
    )),
    ("mcp", (
        "mcp", "connection refused", "no mcp", "tool not found",
        "tool_not_registered", "unity bridge", "blender mcp", "comfyui mcp",
        "8090", "127.0.0.1:8090",
    )),
    ("network", (
        "timeout", "timed out", "connection reset", "connection error",
        "dns", "getaddrinfo", "name resolution", "ssl", "503", "504",
        "bad gateway", "service unavailable", "ECONNRESET", "ECONNREFUSED",
    )),
    ("stalled", (
        "stalled:", "no activity past timeout", "watchdog",
    )),
    ("tool", (
        "tool_invocation_failed", "tool execution failed", "guarded",
        "permission_denied", "denied", "tool error",
    )),
]


# Canonical keys that signal "this JSON is the intended emit_output
# payload" rather than incidental data (e.g. a write_file arg JSON).
# Used by `_rescue_react_emit_output` to guard the "final answer JSON"
# heuristic against false positives.
_EMIT_OUTPUT_SHAPE_KEYS = frozenset({
    "payload",      # explicit emit_output wrapper
    "file_paths",   # almost every Crew schema's required field
    "verdict",      # QA / fail-fast checks
    "issues",       # paired with verdict
    "summary",      # QA's narrative field
    "prompts",      # Art Director's per-path map
    "width", "height",  # image-spec heads
    "imported",     # Technical Artist's import report
    "patched_files",  # contract Debugger
    "added_symbols",
})


def _balanced_brace_extract(text: str, start_after: int = 0) -> list[tuple[int, str]]:
    """Return every balanced `{...}` JSON object substring in `text`
    starting at or after position `start_after`. Tuples are
    (start_index, raw_substring). Used by the rescue heuristics to walk
    candidates without committing to any single one upfront."""
    out: list[tuple[int, str]] = []
    i = start_after
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc = 0, False, False
        for j in range(i, len(text)):
            c = text[j]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    out.append((i, text[i:j + 1]))
                    i = j + 1
                    break
        else:
            # Unbalanced — bail.
            return out
    return out


def _looks_like_emit_payload(d: dict) -> bool:
    """True iff a parsed dict has at least one key from the canonical
    emit_output shape — heuristic guard so we don't promote a random
    write_file argument or LLM scratchpad into a captured payload."""
    return any(k in d for k in _EMIT_OUTPUT_SHAPE_KEYS)


def _unwrap_payload(d: dict) -> dict:
    """emit_output's tool wraps the user-facing dict under "payload".
    Real tool calls write the unwrapped form to set_output; rescue
    needs to match that.

    Two wrapper shapes are handled:
      1. `{"payload": {...}}` — emit_output's own arg signature, sometimes
         echoed back by the agent verbatim.
      2. `{"name": "emit_output", "arguments": {"payload": {...}}}` —
         the OpenAI tool_calls wire format. Qwen / GPT-4 occasionally
         dump this as Final Answer text when they meant to invoke the
         tool natively but CrewAI's ReAct loop captured `content`
         instead. Strip both layers.
    """
    # OpenAI tool-call wire shape — only honour it when name says
    # emit_output, so we don't accidentally unwrap an unrelated tool.
    if d.get("name") == "emit_output":
        args = d.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                args = None
        if isinstance(args, dict):
            d = args  # fall through to payload unwrap
    inner = d.get("payload")
    if isinstance(inner, dict):
        return inner
    return d


def _rescue_react_emit_output(text: str) -> dict | None:
    """Rescue path for Head/Executor steps when the LLM produced its
    emit_output payload as text instead of invoking the tool. CrewAI
    1.14's ReAct parser misses two common patterns we see in
    production (DeepSeek-v4-flash, GPT-4 etc.):

      1. **Action / Action Input** — `Action: emit_output\\nAction Input:
         {...}`. The agent followed ReAct syntax but the LLM emitted
         the Action block in `content` instead of `tool_calls`.

      2. **Final-answer JSON** — the agent ended its loop with a
         markdown-fenced JSON block (often preceded by "I now know the
         final answer" or wrapped in ```json ... ```). CrewAI's
         terminal-answer detector sees the "final answer" signal and
         returns the raw text, never invoking emit_output even though
         the JSON is exactly what should have been passed to it. This
         is the 2026-05-20 TA case from the Butcher debug project —
         the Technical Artist emitted a perfectly valid {file_paths,
         issues} dict but as ```json fenced text.

    Stricter than `_rescue_qa_json` in one way: the extracted JSON
    must look like an emit_output payload (i.e. carry at least one
    canonical schema key). Without this guard we'd happily promote a
    `{"path": "x", "content": ""}` write_file argument into a
    captured payload, papering over a wrong-tool mistake.

    Returns the parsed payload dict (unwrapped from any "payload" key)
    or None if no candidate matches.
    """
    if not text:
        return None
    import re as _re

    # Strategy 1: explicit ReAct Action / Action Input for emit_output.
    if "emit_output" in text:
        m = _re.search(
            r"Action\s*:\s*emit_output\s*\n+\s*Action\s+Input\s*:\s*",
            text, _re.IGNORECASE,
        )
        if m:
            for _start, candidate in _balanced_brace_extract(text, m.end()):
                try:
                    parsed = json.loads(candidate)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(parsed, dict):
                    # For an explicit Action:emit_output match we trust
                    # the agent's intent even if the payload is sparse
                    # (e.g. a tiny {"verdict": "fail"} stub).
                    return _unwrap_payload(parsed)
                break  # first balanced object wasn't a dict; stop.

    # Strategy 2: final-answer / fenced JSON block. Pick the LAST
    # balanced JSON object whose keys match the emit_output shape — if
    # the agent dumped scratchpad JSONs earlier and a real payload at
    # the end, the last one wins.
    candidates = _balanced_brace_extract(text)
    best: dict | None = None
    for _start, candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        unwrapped = _unwrap_payload(parsed)
        if _looks_like_emit_payload(unwrapped):
            best = unwrapped  # keep walking; last shaped match wins
    return best


def _rescue_qa_json(text: str) -> dict | None:
    """Salvage a QA step's intended structured payload when the agent
    forgot to call emit_output and instead dumped the JSON as its
    final answer text. Returns a parsed dict or None.

    Two strategies:
      1. Direct json.loads on the trimmed text.
      2. Find the first ```json ... ``` fenced block and parse that.
      3. Find the first top-level {...} via balanced-brace scan and
         parse it. Handles cases like "Result: { ... } — done".
    """
    if not text:
        return None
    s = text.strip()
    # Strip a leading "```" / "```json" wrapper if present.
    if s.startswith("```"):
        nl = s.find("\n")
        if nl > 0:
            s = s[nl + 1:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    # Strategy 1: direct parse
    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    # Strategy 2: fenced ```json block anywhere in the text
    import re
    m = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    # Strategy 3: balanced-brace scan — find the first {...} that parses
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            return parsed
                    except (json.JSONDecodeError, TypeError):
                        pass
                    break
        start = text.find("{", start + 1)
    return None


# 2026-05-17 P0: agent self-reported failure verdicts that workflow_svc
# must respect. Anything outside this success set (case-insensitive) is
# treated as a failure regardless of structural schema validation.
_VERDICT_PASS = {"pass", "passed", "success", "succeeded", "ok"}


def _rescue_by_file_existence(
    output_paths: list[str] | None,
    project_root: str | None,
) -> dict | None:
    """Synthesize an emit_output-shaped payload from disk state when the
    LLM did the work via tool calls but never reached emit_output.

    Real production case (2026-05-20, system implementation crew):
    Unity Developer agent called `create_script` (writes the .cs via
    Unity MCP) successfully on an earlier ReAct turn, then called
    `find_in_file` to self-verify signatures, then hit max_iter without
    ever invoking `emit_output`. CrewAI returns only the last turn's
    raw_text, captured stays None — but the files are sitting on disk
    just fine.

    Without this rescue, those tasks land as `failed` with a `no_output`
    error even though the next step (script QA) would have happily
    verified the same files. Cascades to "all 3 children failed" on
    the v5 fan-out badge while reality is "all 3 succeeded silently".

    Return shape mirrors a passing emit_output: `{file_paths, summary}`.
    Caller treats this as captured. Returns None when:
      - output_paths is empty (nothing to verify)
      - project_root is missing (no place to look)
      - ANY declared file is missing or empty on disk
    """
    if not output_paths or not project_root:
        return None
    try:
        from pathlib import Path
        root = Path(project_root).resolve()
    except Exception:  # noqa: BLE001
        return None
    confirmed: list[str] = []
    for rel in output_paths:
        if not isinstance(rel, str):
            return None
        try:
            abs_p = (root / rel).resolve()
            abs_p.relative_to(root)  # path-escape guard
        except (ValueError, OSError):
            return None
        if not abs_p.exists() or not abs_p.is_file():
            return None
        try:
            if abs_p.stat().st_size == 0:
                return None
        except OSError:
            return None
        confirmed.append(rel)
    return {
        "file_paths": confirmed,
        "summary": (
            f"自动救起：{len(confirmed)} 个产物文件已在磁盘上存在且非空，"
            "尽管 agent 未显式调用 emit_output（典型场景：max_iter 用完前"
            "先调了 create_script 写文件，没轮到调 emit）。"
        ),
        "_rescued_by": "file_existence",
    }


def _check_claimed_paths_on_disk(
    claimed: list[str] | None,
    project_root: str | None,
) -> tuple[list[str], list[str]]:
    """Server-side disk truth check for executor steps (2026-05-21
    Layer 2 enforcement).

    Given the agent's declared `file_paths` and the project root, return
    `(missing, zero_byte)` — files that don't exist and files that exist
    but have zero bytes. Both are failure conditions: an executor that
    claims a file but produces nothing OR an empty file has not done
    its job.

    Returns `([], [])` when:
      - claimed is empty/None (nothing to check)
      - project_root is missing (no anchor; can't enforce)
      - all files exist and are non-empty

    Integration test diag_layer1_layer2 (2026-05-21) found Qwen with
    Task(output_pydantic=Spec) emits valid ExecutorOutput schema but
    skips all tool calls in 5/5 trials — files don't get written. This
    function plugs that gap. Called from `_run_crew` right after captured
    is finalized; failure raises so the parent task fails with a precise
    error chain.
    """
    if not claimed or not project_root:
        return [], []
    from pathlib import Path as _Path
    root_p = _Path(project_root)
    missing: list[str] = []
    zero_byte: list[str] = []
    for rel in claimed:
        if not isinstance(rel, str) or not rel.strip():
            continue
        s = rel.strip()
        # Disallow path-escape (../../etc/passwd style). Anchor to root.
        candidate = _Path(s) if _Path(s).is_absolute() else (root_p / s)
        try:
            resolved = candidate.resolve()
            root_resolved = root_p.resolve()
            if not str(resolved).startswith(str(root_resolved)):
                # Escaping the project root is treated as missing — we
                # only accept files under the contract's project.
                missing.append(rel)
                continue
            if not candidate.exists():
                missing.append(rel)
                continue
            if candidate.is_file() and candidate.stat().st_size == 0:
                zero_byte.append(rel)
        except (OSError, PermissionError):
            missing.append(rel)
    return missing, zero_byte


def _dedup_errors(errs: list[str]) -> list[str]:
    """Compress a task's error list down to its unique signals.

    The list comes from up to four sources that each say "the same root
    cause" in a different sentence shape:

      - schema validator   ("Assets/X.cs: 文件不存在")
      - QA verdict issues  ("实际 Executor results 为空")
      - contract AST       ("契约要求文件 Assets/X.cs 不存在")
      - debugger patch attempt summary

    Plus a verdict-class header line ("agent self-reported verdict=
    'fail'...") that adds zero information once any concrete issue is
    present. Without compression the canvas tooltip and the failure
    analyser see 4-7 lines that all encode 1-2 facts; users (rightly)
    perceive it as duplicate noise.

    Three-layer reduction, order-preserving:

    1. Drop the bare "agent self-reported verdict=…" header line when
       any other entry exists (it's a class marker, not information).
    2. Substring dedup on the punctuation-stripped, lowercased text —
       short lines that are subsequences of longer ones disappear; the
       longer wrapper survives (replaces the shorter when seen later).
    3. Signature dedup — extract the (path|token) bag from each line
       and the FIRST semantic action keyword present
       (不存在 / 缺失 / missing / not_found / 为空 / empty / 尺寸不匹配
       / mismatch / actual_…). Two lines with identical signature
       collapse to the longer of the two. This is what catches the
       file-missing cluster across paraphrases.
    """
    if not errs:
        return []
    import re

    _PUNCT = re.compile(r"[\s：:；;。，,.()（）'\"`]+")
    _PATH_RE = re.compile(r"[A-Za-z][\w./\\-]*\.[a-zA-Z]{2,4}")
    _ACTION_KEYS: tuple[tuple[str, str], ...] = (
        ("不存在", "missing"),
        ("缺失", "missing"),
        ("missing", "missing"),
        ("not found", "missing"),
        ("not_found", "missing"),
        ("为空", "empty"),
        ("empty", "empty"),
        ("尺寸不匹配", "size_mismatch"),
        ("size mismatch", "size_mismatch"),
        ("dimension mismatch", "size_mismatch"),
        ("kind 不符", "kind_mismatch"),
        ("kind mismatch", "kind_mismatch"),
        ("verdict='fail'", "verdict_fail"),
        ("verdict=\"fail\"", "verdict_fail"),
    )
    _VERDICT_HEADER_RE = re.compile(
        r"agent self.?reported verdict.*treated as failure", re.IGNORECASE,
    )

    def norm(s: str) -> str:
        return _PUNCT.sub("", s.lower())

    def signature(s: str) -> str | None:
        lower = s.lower()
        action: str | None = None
        for needle, key in _ACTION_KEYS:
            if needle.lower() in lower:
                action = key
                break
        if not action:
            return None
        paths = sorted({m.lower() for m in _PATH_RE.findall(s)})
        return f"{action}|{'|'.join(paths)}"

    # Step 1: filter input.
    cleaned: list[str] = []
    has_concrete = any(
        isinstance(e, str) and e.strip() and not _VERDICT_HEADER_RE.search(e)
        for e in errs
    )
    for raw in errs:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s:
            continue
        if has_concrete and _VERDICT_HEADER_RE.search(s):
            continue  # drop the class-marker header
        cleaned.append(s)

    # Step 2 + 3: substring + signature dedup combined.
    out: list[str] = []
    out_norm: list[str] = []
    out_sig: list[str | None] = []
    for s in cleaned:
        n = norm(s)
        if not n:
            continue
        sig = signature(s)
        dropped = False
        for i, kept_n in enumerate(out_norm):
            kept_sig = out_sig[i]
            # Substring collapse.
            if n == kept_n or n in kept_n:
                dropped = True
                break
            if kept_n in n:
                out[i] = s
                out_norm[i] = n
                out_sig[i] = sig
                dropped = True
                break
            # Signature collapse — same root fact, different wording.
            if sig and kept_sig and sig == kept_sig:
                # Keep the longer entry (usually carries more detail).
                if len(s) > len(out[i]):
                    out[i] = s
                    out_norm[i] = n
                    out_sig[i] = sig
                dropped = True
                break
        if not dropped:
            out.append(s)
            out_norm.append(n)
            out_sig.append(sig)
    return out


def _collect_verdict_errors(extracted: dict) -> list[str]:
    """If the captured payload includes a `verdict` field whose value
    isn't one of the known-good tokens, treat the task as failed and
    pull as much context out as we can:

      - the raw verdict value
      - up to 5 entries from the agent's `issues` field, with severity
        prefixes preserved so the canvas tooltip and failure_analyzer
        both have actionable text
      - the `summary` line (if present) as a fallback when issues is
        empty

    Returns an empty list if the verdict is missing (legacy outputs
    that didn't declare one) or marks pass. Callers append the
    returned list to the existing `errors` so the normal
    validation_failed branch handles persistence / UI / debugger
    hand-off uniformly.
    """
    if not isinstance(extracted, dict):
        return []
    raw_verdict = extracted.get("verdict")
    if raw_verdict is None:
        return []
    verdict = str(raw_verdict).strip().lower()
    if not verdict or verdict in _VERDICT_PASS:
        return []

    out: list[str] = [
        f"agent self-reported verdict='{raw_verdict}' (treated as failure)"
    ]
    issues = extracted.get("issues")
    if isinstance(issues, list):
        for iss in issues[:5]:
            if isinstance(iss, dict):
                sev = str(iss.get("severity", "")).upper()
                detail = (iss.get("detail")
                          or iss.get("message")
                          or iss.get("description")
                          or "")
                if not detail:
                    continue
                detail = str(detail)[:240]
                out.append(f"[{sev}] {detail}" if sev else detail)
            elif isinstance(iss, str) and iss.strip():
                out.append(iss.strip()[:240])
    if len(out) == 1:  # no issues parsed — use summary as the body
        summary = extracted.get("summary")
        if isinstance(summary, str) and summary.strip():
            out.append(summary.strip()[:240])
    return out


def _extract_output_paths(output_schema: dict, _detail: str = "") -> list[str]:
    """Best-effort recovery of the PM contract's output_paths list.

    PM v3/v4 stores the expected file paths inside output_schema under
    `properties.file_paths.const` or `properties.file_paths.examples`,
    and sometimes also lists them in plain text inside task.detail.
    The Crew runner pipes this into every step's prompt so Head/Executor
    agents see exactly what they're contractually obliged to produce.

    Returns [] if nothing concrete is found — downstream steps still get
    the raw output_schema as a fallback.
    """
    paths: list[str] = []
    if isinstance(output_schema, dict):
        props = output_schema.get("properties") or {}
        for key in ("file_paths", "output_paths", "paths"):
            entry = props.get(key) or {}
            if isinstance(entry, dict):
                for candidate_key in ("const", "default", "examples"):
                    val = entry.get(candidate_key)
                    if isinstance(val, list):
                        paths.extend(p for p in val if isinstance(p, str) and p.strip())
                    elif isinstance(val, str) and val.strip():
                        paths.append(val.strip())
        # Sometimes the contract is at top level
        top_val = output_schema.get("required_paths")
        if isinstance(top_val, list):
            paths.extend(p for p in top_val if isinstance(p, str))
    # Dedup while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def _classify_task_error(err: str) -> str:
    """Return a short kind label so the frontend can render a specific
    Chinese hint on hover instead of just \"执行失败\".

    Falls back to \"unknown\" if no pattern matched."""
    if not err:
        return "unknown"
    lower = err.lower()
    for kind, patterns in _ERROR_KIND_PATTERNS:
        for p in patterns:
            if p.lower() in lower:
                return kind
    return "unknown"


# Stage D (2026-05-19): split a contract-validator error list into
# "Debugger-patchable" vs "needs full retry". Patchable = missing
# signature inside an already-existing .cs file (a surgical add).
# NOT patchable = file doesn't exist (need full Executor re-run) or
# parse failed (the .cs has syntax errors a full retry is more likely
# to fix than a targeted patch).
_CONTRACT_PATCHABLE_PATTERNS = (
    "缺少契约签名",  # the AST validator's canonical missing-sig prefix
)
_CONTRACT_UNPATCHABLE_PATTERNS = (
    "文件不存在",      # Crew Executor never wrote the file → full re-run
    "解析失败",        # syntax error → full re-run more likely to help
    "读取失败",        # IO error → not a content issue
    "无法解析",        # contract sig itself unparseable — PM bug
)


def _schema_requires_file_paths(schema: Any) -> bool:
    """True iff the JSON Schema declares `file_paths` in its required
    list. Used by the deterministic emit_output synth to confirm the
    synth actually answers the field the workflow is about to demand."""
    if not isinstance(schema, dict):
        return False
    req = schema.get("required") or []
    return isinstance(req, list) and "file_paths" in req


def _contract_errors_patchable_by_debugger(errors: list[str]) -> list[str]:
    """Filter contract_validator errors to the subset where a single
    Debugger patch round is likely to succeed.

    Returns the patchable subset. Caller decides whether to attempt
    repair only if EVERY error is patchable (i.e. the returned list
    has the same length as `errors`) — partial-patch is a slippery
    slope (the unpatchable issues will still fail validation later)."""
    if not errors:
        return []
    out: list[str] = []
    for e in errors:
        s = str(e or "")
        if any(p in s for p in _CONTRACT_UNPATCHABLE_PATTERNS):
            continue
        if any(p in s for p in _CONTRACT_PATCHABLE_PATTERNS):
            out.append(s)
    return out


class WorkflowService:
    def __init__(self) -> None:
        self._active: dict[str, HarnessStateMachine] = {}
        self._runners: dict[str, TaskRunner] = {}
        self._run_tasks: dict[str, asyncio.Task] = {}
        self._outputs: dict[str, dict[str, dict]] = {}
        # Per-project asyncio.Lock — serialises start/pause/resume/abort/retry
        # for the same project so a double-click Start or a concurrent
        # retry can't produce two harnesses or duplicate asyncio.Tasks.
        # Lazily created in _get_project_lock(); the lock map itself is
        # mutated only on the main event loop (FastAPI request handlers),
        # so dict mutation is single-threaded.
        # Audit (2026-05-16 architecture-audit.md, Top 5 #3) called out
        # the TOCTOU race here as P1; this is the fix.
        self._project_locks: dict[str, asyncio.Lock] = {}
        # Stage D (2026-05-19): track which tasks already got an in-band
        # Debugger contract-patch attempt within the current process.
        # Bounded to one shot per task per process — a user-initiated
        # retry (which clears artifacts) resets this implicitly: the
        # task_id stays in the set, but the cleanup deletes the .cs
        # files so the next Crew run rebuilds from scratch + may patch
        # again only after another fresh failure (not double-firing on
        # the same Crew output).
        self._contract_debugger_attempts: set[str] = set()

    def _get_project_lock(self, project_id: str) -> asyncio.Lock:
        lock = self._project_locks.get(project_id)
        if lock is None:
            lock = asyncio.Lock()
            self._project_locks[project_id] = lock
        return lock

    # ── Public API ────────────────────────────────────────
    # Every state-mutating entry point grabs the per-project lock first
    # so start/pause/resume/abort/retry_task on the same project_id are
    # serialised. Concurrent requests on DIFFERENT projects still run
    # in parallel.

    async def start(
        self,
        project_id: str,
        *,
        root_parent_path: str | None = None,
        slug: str | None = None,
    ) -> None:
        """Begin (or continue) a project run.

        For projects with scaffold_status='pending', the caller MUST
        supply `root_parent_path` (user-picked parent dir) and `slug`
        (English project-folder name). The cloner runs in a background
        task; this call returns immediately. Frontend tracks progress
        via WS `project.scaffold_*` events and the existing scaffold
        column on the project row.

        Keeps the lock thin so the test surface (which mocks
        _start_locked) only needs the lock semantics to be preserved.
        """
        async with self._get_project_lock(project_id):
            await self._start_locked(
                project_id,
                root_parent_path=root_parent_path,
                slug=slug,
            )

    async def scaffold_only(
        self,
        project_id: str,
        root_parent_path: str,
        slug: str,
        *,
        overwrite: bool = False,
    ) -> None:
        """Run a git clone for the bound Unity template, WITHOUT
        continuing to start the workflow. Fire-and-forget — caller
        returns to user immediately; UI tracks progress via the
        project.scaffold_* WS events.

        2026-05-17 redesign: replaces _scaffold_then_start. Triggered
        from the ProjectCard 「路径」 button (POST /workflow/projects/
        {id}/scaffold) and the repair flow (POST /scaffold-repair with
        overwrite=True). On success: scaffold_status='done' — but no
        automatic start. User clicks 开始 on the task page separately.
        """
        project = await crud.get_by_id("projects", project_id)
        if not project:
            log.warning("scaffold_only.project_missing", project_id=project_id)
            return
        template_id = project.get("template_id") or ""

        from services.template_cloner_svc import (
            clone_template,
            mark_scaffold_status,
            update_project_root,
            ScaffoldError,
        )
        from api.ws import manager as ws_manager

        await crud.update_by_id("projects", project_id, {
            "root_parent_path": root_parent_path,
        })
        await mark_scaffold_status(project_id, "in_progress")

        async def _broadcast(stage: str, message: str) -> None:
            try:
                await ws_manager.broadcast("project.scaffold_progress", {
                    "project_id": project_id,
                    "stage": stage,
                    "message": message,
                })
            except Exception:
                pass  # WS issues must never break the clone path

        try:
            verb = "修复并重新构建" if overwrite else "构建"
            await _broadcast("starting", f"开始{verb}项目雏形（{slug}）…")
            new_root = await clone_template(
                project_id,
                template_id=template_id,
                parent_dir=root_parent_path,
                project_slug=slug,
                on_progress=_broadcast,
                overwrite=overwrite,
            )
            await update_project_root(project_id, new_root)
            await mark_scaffold_status(project_id, "done")
            await ws_manager.broadcast("project.scaffold_complete", {
                "project_id": project_id,
                "root_path": str(new_root),
            })
            log.info("workflow.scaffold_complete",
                     project_id=project_id,
                     root_path=str(new_root),
                     overwrite=overwrite)
        except ScaffoldError as exc:
            await mark_scaffold_status(project_id, "failed")
            try:
                await ws_manager.broadcast("project.scaffold_failed", {
                    "project_id": project_id,
                    "error": str(exc),
                })
            except Exception:
                pass
            log.error("workflow.scaffold_failed",
                      project_id=project_id, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            await mark_scaffold_status(project_id, "failed")
            try:
                await ws_manager.broadcast("project.scaffold_failed", {
                    "project_id": project_id,
                    "error": f"未预期错误：{exc}",
                })
            except Exception:
                pass
            log.error("workflow.scaffold_unhandled",
                      project_id=project_id, error=str(exc))

    async def _start_locked(
        self,
        project_id: str,
        *,
        # Legacy kwargs from the old "scaffold via start" flow — still
        # accepted so old tests keep their signature compatible, but
        # they no longer affect behavior. Scaffold now lives on its own
        # POST /workflow/projects/{id}/scaffold route triggered by the
        # ProjectCard 「路径」 button.
        root_parent_path: str | None = None,  # noqa: ARG002 — kept for legacy callers
        slug: str | None = None,  # noqa: ARG002
    ) -> None:
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(f"Project {project_id} not found")

        # V5+ scaffold gate. 2026-05-17 redesign: start() no longer
        # triggers the clone. If user hasn't scaffolded yet, refuse with
        # a clear pointer to the ProjectCard's path button. If scaffold
        # is mid-flight, refuse with "wait". scaffold_status==None means
        # non-Unity project (no scaffold needed) → falls through to the
        # normal start path.
        scaffold_status = project.get("scaffold_status")
        if scaffold_status in ("pending", "failed"):
            raise ValueError(
                "项目尚未脚手架。请回主页点项目卡片【路径】按钮，"
                "选好父目录 + 英文项目名后再来启动。"
            )
        if scaffold_status == "in_progress":
            raise ValueError("项目正在构建雏形，请等待完成后再启动")

        tasks = await self._load_tasks(project_id)
        if not tasks:
            raise ValueError(f"Project {project_id} has no tasks")

        # 2026-05-17 Plan C sanity guard: surface PM contract corruption
        # before kicking off any Crew. A Crew task whose output_paths
        # came back empty means Phase 4's `path_specs` were dropped (the
        # legacy project_svc INSERT bug, fixed in commit "feat(pm): persist
        # output_paths") or the LLM produced nothing. Without this warning
        # the Executor will see "[]" and exit silently with zero files,
        # like the 魔塔 audio task did. We don't block start() — for some
        # legacy rows the user may want to push through anyway — but we
        # do log a loud warning the Log drawer will surface.
        for t in tasks:
            if t.get("performer_kind") != "crew":
                continue
            raw = t.get("output_paths")
            paths_list: list = []
            if isinstance(raw, str) and raw:
                try:
                    paths_list = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    paths_list = []
            elif isinstance(raw, list):
                paths_list = raw
            if not paths_list:
                log.warning(
                    "workflow.start.crew_task_missing_output_paths",
                    project_id=project_id,
                    task_id=t.get("id"),
                    title=t.get("title"),
                    hint="PM Phase 4 path_specs were not persisted; Crew Executor will fall back to task.detail",
                )

        # Reject projects where any task has no executable performer
        # bound. PM v4 tasks bind via performer_kind + performer_id;
        # legacy / setup / iterate tasks still use the agent_id column
        # alone (workflow_svc._run_agent falls back to it when
        # performer_kind is null). A task is "assignable" when at least
        # one of those two channels names a real id — anything else means
        # Phase 5 didn't pick anyone and we'd crash on dispatch.
        #
        # Wire-level guarantee: every code path that calls start() —
        # frontend pre-check, retry flows, scheduler — gets the same rule.
        def _has_performer(t: dict) -> bool:
            kind = t.get("performer_kind")
            if kind == "crew" and t.get("performer_id"):
                return True
            # 'agent' kind OR legacy null kind: either column counts.
            return bool(t.get("agent_id") or t.get("performer_id"))

        missing_perf = [t for t in tasks if not _has_performer(t)]
        if missing_perf:
            titles = ", ".join(t.get("title", "未命名") for t in missing_perf)
            raise ValueError(
                f"以下任务未指定执行者（Agent/Crew），无法启动：{titles}",
            )

        dag_errors = validate_dag(tasks)
        if dag_errors:
            error_msgs = [e.message for e in dag_errors]
            raise ValueError(f"DAG validation failed: {'; '.join(error_msgs)}")

        harness = HarnessStateMachine(
            project_id=project_id,
            state=ProjectState(project.get("state", "ready")),
            tasks=tasks,
        )
        runner = TaskRunner(tasks)

        events = harness.start()

        self._active[project_id] = harness
        self._runners[project_id] = runner
        self._outputs[project_id] = {}

        await self._persist_project_state(project_id, harness)
        await self._persist_all_task_states(project_id, harness)
        await event_bus.publish_all(events)

        self._schedule_ready_tasks(project_id, harness, runner)

        log.info("workflow.started", project_id=project_id)

    async def pause(self, project_id: str) -> None:
        async with self._get_project_lock(project_id):
            await self._pause_locked(project_id)

    async def _pause_locked(self, project_id: str) -> None:
        # Live-harness path — normal in-session pause
        harness = self._active.get(project_id)
        if harness is not None:
            events = harness.pause()
            await self._persist_project_state(project_id, harness)
            await self._persist_all_task_states(project_id, harness)
            await event_bus.publish_all(events)
            log.info("workflow.paused", project_id=project_id)
            return

        # Orphan path — project was running before backend restart, so
        # there's no harness in memory. Reconcile directly: stop scheduling,
        # flip state to paused. Without this fallback the pause button
        # silently 404s on any project that survived a backend restart.
        from infra.repo import crud
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(project_id)
        # Mark any still-running task rows as paused so the UI matches
        running_tasks = await crud.get_all(
            "tasks", "project_id = ? AND status = ?", (project_id, "running"),
        )
        for t in running_tasks:
            await crud.update_by_id("tasks", t["id"], {"status": "paused"})
        await crud.update_by_id("projects", project_id, {
            "state": "paused",
            "is_running": 0,
        })
        log.info("workflow.paused_orphan",
                 project_id=project_id, tasks_flipped=len(running_tasks))

    async def resume(self, project_id: str) -> None:
        async with self._get_project_lock(project_id):
            await self._resume_locked(project_id)

    async def _resume_locked(self, project_id: str) -> None:
        # Live-harness path — normal in-session resume
        harness = self._active.get(project_id)
        if harness is not None:
            events = harness.resume()

            await self._persist_project_state(project_id, harness)
            await self._persist_all_task_states(project_id, harness)
            await event_bus.publish_all(events)

            runner = self._runners[project_id]
            self._schedule_ready_tasks(project_id, harness, runner)

            log.info("workflow.resumed", project_id=project_id)
            return

        # Orphan path — symmetric with _pause_locked. After a backend
        # restart (uvicorn --reload or a full kill) the harness is gone
        # but the project row in DB still says paused. Without this
        # branch the resume button 404s silently and the user thinks
        # the button is broken. Rebuild the harness from DB the same
        # way _start_locked does, then call harness.resume() to
        # transition PAUSED → RUNNING and re-schedule ready tasks.
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(project_id)

        tasks = await self._load_tasks(project_id)
        if not tasks:
            raise ValueError(f"Project {project_id} has no tasks")

        harness = HarnessStateMachine(
            project_id=project_id,
            state=ProjectState(project.get("state", "paused")),
            tasks=tasks,
        )
        runner = TaskRunner(tasks)

        events = harness.resume()

        self._active[project_id] = harness
        self._runners[project_id] = runner
        self._outputs.setdefault(project_id, {})

        await self._persist_project_state(project_id, harness)
        await self._persist_all_task_states(project_id, harness)
        await event_bus.publish_all(events)

        self._schedule_ready_tasks(project_id, harness, runner)

        log.info("workflow.resumed_orphan", project_id=project_id)

    async def abort(self, project_id: str, reason: str = "") -> None:
        async with self._get_project_lock(project_id):
            await self._abort_locked(project_id, reason)

    async def _abort_locked(self, project_id: str, reason: str = "") -> None:
        # Live-harness path
        harness = self._active.get(project_id)
        if harness is not None:
            events = harness.abort(reason)
            await self._persist_project_state(project_id, harness)
            await self._persist_all_task_states(project_id, harness)
            await event_bus.publish_all(events)
            self._cleanup_project(project_id)
            log.info("workflow.aborted",
                     project_id=project_id, reason=reason)
            return

        # Orphan path — same idea as pause(): user wants to give up on a
        # project that survived a backend restart. Without this fallback
        # the abort button 404s and the project stays "stuck" forever.
        from infra.repo import crud
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(project_id)
        non_terminal = await crud.get_all(
            "tasks",
            "project_id = ? AND status NOT IN ('done','failed','aborted','validation_failed')",
            (project_id,),
        )
        for t in non_terminal:
            await crud.update_by_id("tasks", t["id"], {"status": "aborted"})
        await crud.update_by_id("projects", project_id, {
            "state": "aborted",
            "is_running": 0,
        })
        log.info("workflow.aborted_orphan",
                 project_id=project_id, tasks_aborted=len(non_terminal),
                 reason=reason)

    async def reset_project(
        self,
        project_id: str,
        *,
        delete_output_files: bool = False,
    ) -> dict:
        """Hard-reset a project to its initial state.

        - All tasks → status='pending', error fields / timestamps / IO
          refs / failure_analysis / fan-out parent_step_index cleared.
        - Project → state='ready', is_running=0, progress_pct=0.
        - MyCrew artifacts at OUTPUT_DIR/<pid>/ wiped entirely.
        - The in-memory `_active` entry dropped so the next start
          rebuilds the harness from DB.
        - When `delete_output_files=True`, also walks every task's
          `output_paths` and unlinks the file under `root_path/...`.
          Use this for debug-only projects where each test starts from
          an empty workspace.

        Returns a summary dict for the API response. Raises KeyError if
        the project doesn't exist.
        """
        from bootstrap.paths import OUTPUT_DIR
        import shutil

        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(f"Project {project_id} not found")

        tasks = await crud.get_all(
            "tasks", "project_id = ?", (project_id,),
        )

        # Phase 1: DB reset — tasks first, then project.
        reset_fields = {
            "status": "pending",
            "io_in_ref": None,
            "io_out_ref": None,
            "last_error": None,
            "last_error_kind": None,
            "validation_errors": None,
            "failure_analysis": None,
            "failure_analysis_at": None,
            "started_at": None,
            "finished_at": None,
            "last_activity_at": None,
            "last_run_started_at": None,
            "qa_score": None,
            "parent_step_index": None,
        }
        for t in tasks:
            await crud.update_by_id("tasks", t["id"], reset_fields)

        await crud.update_by_id("projects", project_id, {
            "state": "ready",
            "is_running": 0,
            "progress_pct": 0,
            "runtime_started_at": None,
        })

        # Phase 2: filesystem cleanup.
        proj_output = OUTPUT_DIR / project_id
        artifacts_removed = False
        if proj_output.exists():
            try:
                shutil.rmtree(proj_output)
                artifacts_removed = True
            except OSError as exc:
                log.warning(
                    "workflow.reset_artifacts_failed",
                    project_id=project_id, error=str(exc),
                )

        produced_files_removed: list[str] = []
        if delete_output_files and project.get("root_path"):
            from pathlib import Path
            root = Path(project["root_path"]).resolve()
            for t in tasks:
                paths_raw = t.get("output_paths")
                if not paths_raw:
                    continue
                try:
                    paths = (
                        paths_raw if isinstance(paths_raw, list)
                        else json.loads(paths_raw)
                    )
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(paths, list):
                    continue
                for rel in paths:
                    if not isinstance(rel, str):
                        continue
                    try:
                        abs_p = (root / rel).resolve()
                        abs_p.relative_to(root)  # path-escape guard
                    except (ValueError, OSError):
                        continue
                    if abs_p.exists() and abs_p.is_file():
                        try:
                            abs_p.unlink()
                            # Companion .meta files (Unity) get the same
                            # treatment so retry doesn't see stale GUID
                            # links.
                            meta = abs_p.with_suffix(abs_p.suffix + ".meta")
                            if meta.exists():
                                meta.unlink()
                            produced_files_removed.append(rel)
                        except OSError as exc:
                            log.warning(
                                "workflow.reset_unlink_failed",
                                project_id=project_id, path=str(abs_p),
                                error=str(exc),
                            )

        # Phase 3: drop the in-memory harness + runner so the next
        # start rebuilds them from the now-clean DB.
        self._active.pop(project_id, None)
        self._runners.pop(project_id, None)
        self._outputs.pop(project_id, None)
        self._contract_debugger_attempts = {
            tid for tid in self._contract_debugger_attempts
            if not any(t["id"] == tid for t in tasks)
        }

        log.info(
            "workflow.project_reset",
            project_id=project_id,
            tasks_reset=len(tasks),
            artifacts_removed=artifacts_removed,
            files_removed=len(produced_files_removed),
        )
        return {
            "project_id": project_id,
            "tasks_reset": len(tasks),
            "artifacts_removed": artifacts_removed,
            "produced_files_removed": produced_files_removed,
        }

    async def retry_task(
        self,
        project_id: str,
        task_id: str,
        cleanup_artifacts: bool = True,
    ) -> None:
        """Re-run a failed task.

        ``cleanup_artifacts`` (Stage B, 2026-05-16): when true (the
        default), wipe ``<OUTPUT_DIR>/<pid>/<tid>/{sub,out.json,out.md}``
        before re-scheduling. Without cleanup, the previous run's residue
        can pass emit_output's path-existence check (the agent claims new
        paths that *happen* to still be on disk) — that's the stale-state
        trap Stage B is built to close. Users who set this false from the
        confirm dialog explicitly opt into "keep the residue and rerun
        anyway" — useful when the previous emit_output was correct but a
        downstream step failed.

        Auto-resume: if the project's harness was lost (backend restart
        after the original failure, project state `stalled` / `failed`),
        we rebuild it from the DB instead of 404-ing. Previously a user
        hitting Retry after a restart silently saw nothing happen because
        the route raised KeyError("Project not active").
        """
        async with self._get_project_lock(project_id):
            await self._ensure_active(project_id)
            harness = self._get_harness(project_id)
            runner = self._runners[project_id]

            if cleanup_artifacts:
                await self._cleanup_task_artifacts(project_id, task_id)

            events = harness.retry_task(task_id)
            await self._persist_task_state(project_id, task_id, harness)
            await event_bus.publish_all(events)

            self._schedule_task(project_id, task_id, harness, runner)

    async def _ensure_active(self, project_id: str) -> None:
        """Make sure `_active[project_id]` is populated; rebuild from DB
        if not. Idempotent — already-active projects are a no-op.

        Preserves on-disk task statuses (done / failed / etc) so the
        rebuilt harness reflects reality, not a fresh start. We avoid
        calling harness.start() here because that would broadcast
        ProjectStarted and try to activate ready tasks; the caller
        (retry_task, manual rerun, etc.) drives what gets scheduled.
        """
        if project_id in self._active:
            return
        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(f"Project {project_id} not found")
        tasks = await self._load_tasks(project_id)
        if not tasks:
            raise ValueError(f"Project {project_id} has no tasks")

        # Build harness in whatever state the project is currently in.
        # If it was 'stalled' or 'failed', we flip to RUNNING below so
        # the scheduler can fire — caller has decided this project is
        # active again by virtue of asking to retry a task.
        harness = HarnessStateMachine(
            project_id=project_id,
            state=ProjectState(project.get("state", "ready")),
            tasks=tasks,
        )
        runner = TaskRunner(tasks)

        # Rehydrate completed task outputs so downstream retries can
        # find their upstream context (TaskInput.upstream_outputs).
        outputs: dict[str, dict] = {}
        from bootstrap.paths import OUTPUT_DIR
        for t in tasks:
            if t.get("status") != "done":
                continue
            out_path = OUTPUT_DIR / project_id / t["id"] / "out.json"
            if not out_path.exists():
                continue
            try:
                outputs[t["id"]] = json.loads(out_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

        # Flip project to RUNNING if it wasn't already — this is the
        # implicit "resume" that gets us out of stalled/failed terminal-
        # looking states without forcing the user to click Start.
        if harness.state != ProjectState.RUNNING:
            harness._transition_project(ProjectState.RUNNING)
            await crud.update_by_id("projects", project_id, {
                "state": "running",
                "is_running": 1,
            })

        self._active[project_id] = harness
        self._runners[project_id] = runner
        self._outputs[project_id] = outputs
        log.info("workflow.auto_resumed_for_retry",
                 project_id=project_id,
                 rehydrated_outputs=len(outputs))

    async def _cleanup_task_artifacts(
        self, project_id: str, task_id: str,
    ) -> None:
        """Remove a task's previous outputs so the next run starts clean.

        Two passes:
          1. **MyCrew side** (``<OUTPUT_DIR>/<pid>/<tid>``): wipe the
             ``sub/`` directory and the ``out.json`` / ``out.md`` pair;
             leave ``in.md`` / ``in.json`` intact (they describe the
             task itself, not its previous output).
          2. **Project side** (``<project_root>/...``): delete every
             real artifact file the previous run produced at the
             paths listed in ``task.output_paths``, plus the Unity
             ``.meta`` sibling of each. Without this, a retry can hit
             the stale-state trap: the new run sees the *previous*
             ``.cs`` / ``.png`` / ``.wav`` already on disk, satisfies
             the path-existence + size-magic-header sanity checks, and
             reports success without actually regenerating anything.
             (See incident analysis 2026-05-19.)

        Guards:
          - Resolved paths must stay under ``project_root`` (path
            escape protection).
          - Paths shared with another task in the same project are
            skipped — the other task still owns them.
          - ``in.md`` / ``in.json`` (task input cache) are never touched
            since they're regenerated each run.

        The task row's ``io_out_ref`` column is cleared in the same pass
        so the IO viewer doesn't display a path that no longer exists.
        """
        import shutil
        from bootstrap.paths import OUTPUT_DIR

        task_dir = OUTPUT_DIR / project_id / task_id
        removed: list[str] = []

        # ── 1. MyCrew-side: sub/ + out.json/md ────────────────────
        sub_dir = task_dir / "sub"
        if sub_dir.exists():
            try:
                shutil.rmtree(sub_dir)
                removed.append("sub/")
            except OSError as exc:
                log.warning("retry.cleanup_sub_failed",
                            task_id=task_id, error=str(exc))
        for name in ("out.json", "out.md"):
            f = task_dir / name
            if f.exists():
                try:
                    f.unlink()
                    removed.append(name)
                except OSError as exc:
                    log.warning("retry.cleanup_file_failed",
                                task_id=task_id, file=name, error=str(exc))

        # ── 2. Project-side: task.output_paths under project_root ─
        await self._cleanup_task_output_paths(
            project_id, task_id, removed,
        )

        # Clear the DB pointer so the IO viewer doesn't tease a stale file.
        try:
            await crud.update_by_id("tasks", task_id, {"io_out_ref": None})
        except Exception as exc:  # noqa: BLE001
            log.warning("retry.cleanup_db_clear_failed",
                        task_id=task_id, error=str(exc))

        log.info("retry.artifacts_cleaned",
                 task_id=task_id, removed=removed or ["(nothing)"])

    async def _cleanup_task_output_paths(
        self, project_id: str, task_id: str, removed_acc: list[str],
    ) -> None:
        """Delete the real artifact files this task wrote on the previous
        run (under <project_root>), plus their .meta siblings.

        Mutates ``removed_acc`` so the caller can log a unified list.
        Never raises — every failure is logged and skipped.
        """
        from pathlib import Path

        project = await crud.get_by_id("projects", project_id) or {}
        project_root_str = project.get("root_path") or ""
        if not project_root_str:
            return  # No root bound yet → no project-side files exist.
        try:
            project_root = Path(project_root_str).resolve()
        except (OSError, ValueError):
            return
        if not project_root.exists():
            return

        task = await crud.get_by_id("tasks", task_id) or {}
        raw = task.get("output_paths") or "[]"
        try:
            paths_list = (
                json.loads(raw) if isinstance(raw, str) else raw
            )
        except (json.JSONDecodeError, TypeError):
            paths_list = []
        if not isinstance(paths_list, list) or not paths_list:
            return

        # Find paths shared with OTHER tasks in this project — skip them
        # (they belong to other tasks, deleting them would corrupt those).
        # PM v5's _validate_path_specs already forbids cross-task path
        # collisions at planning time, so the shared set is normally
        # empty; this is belt-and-braces for legacy data.
        shared: set[str] = set()
        try:
            other_tasks = await crud.get_all(
                "tasks", "project_id = ? AND id != ?",
                (project_id, task_id),
            )
            for ot in other_tasks or []:
                other_raw = ot.get("output_paths") or "[]"
                try:
                    other_list = (
                        json.loads(other_raw)
                        if isinstance(other_raw, str) else other_raw
                    )
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(other_list, list):
                    shared.update(str(p) for p in other_list)
        except Exception as exc:  # noqa: BLE001
            log.warning("retry.cleanup_shared_lookup_failed",
                        task_id=task_id, error=str(exc))

        for rel_path in paths_list:
            if not isinstance(rel_path, str) or not rel_path.strip():
                continue
            if rel_path in shared:
                log.info("retry.cleanup_skipped_shared",
                         task_id=task_id, path=rel_path)
                continue
            try:
                candidate = (project_root / rel_path).resolve()
                # Path escape guard: must stay under project_root.
                candidate.relative_to(project_root)
            except (ValueError, OSError) as exc:
                log.warning("retry.cleanup_path_escape",
                            task_id=task_id, path=rel_path,
                            error=str(exc))
                continue
            for f in (
                candidate,
                candidate.with_suffix(candidate.suffix + ".meta"),
            ):
                if not f.is_file():
                    continue
                try:
                    f.unlink()
                    removed_acc.append(
                        str(f.relative_to(project_root)).replace("\\", "/")
                    )
                except OSError as exc:
                    log.warning("retry.cleanup_output_failed",
                                task_id=task_id, file=str(f),
                                error=str(exc))

    async def recover(self) -> list[str]:
        rows = await crud.get_all("projects", "state = ?", (ProjectState.RUNNING,))
        recovered = []
        for row in rows:
            try:
                await self.start(row["id"])
                recovered.append(row["id"])
            except Exception as exc:
                log.error("workflow.recover_failed",
                          project_id=row["id"], error=str(exc))
        return recovered

    async def pause_all(self) -> int:
        count = 0
        for project_id in list(self._active.keys()):
            try:
                await self.pause(project_id)
                count += 1
            except Exception:
                pass
        return count

    def get_active_projects(self) -> list[str]:
        return list(self._active.keys())

    # ── Task execution ────────────────────────────────────

    def _schedule_ready_tasks(self, project_id: str,
                               harness: HarnessStateMachine,
                               runner: TaskRunner) -> None:
        for task in harness.get_running_tasks():
            self._schedule_task(project_id, task["id"], harness, runner)

    def _schedule_task(self, project_id: str, task_id: str,
                        harness: HarnessStateMachine,
                        runner: TaskRunner) -> None:
        key = f"{project_id}:{task_id}"
        if key in self._run_tasks:
            return
        coro = self._execute_task(project_id, task_id, harness, runner)
        self._run_tasks[key] = asyncio.create_task(coro)

    async def _execute_task(self, project_id: str, task_id: str,
                             harness: HarnessStateMachine,
                             runner: TaskRunner) -> None:
        key = f"{project_id}:{task_id}"
        try:
            completed_outputs = self._outputs.get(project_id, {})
            task_input = runner.prepare_input(task_id, completed_outputs)

            # Debugger short-circuit: when final_qa already reported
            # verdict="pass" there's nothing to debug, so we skip the
            # LLM call entirely and mark the task done with a
            # synthesised summary. Saves a Crew-budget round of tokens
            # on every clean project. Implemented here (not in
            # prepare_input) so the IO viewer still has a real in.md.
            if task_input.kind == "debugger":
                fast_path = await self._maybe_skip_debugger(task_input)
                if fast_path is not None:
                    if project_id not in self._outputs:
                        self._outputs[project_id] = {}
                    self._outputs[project_id][task_id] = fast_path
                    await self._save_task_input(project_id, task_id, task_input)
                    await self._save_task_output(
                        project_id, task_id,
                        TaskOutput(task_id=task_id, raw_text="",
                                   structured=fast_path),
                    )
                    await crud.update_by_id("tasks", task_id, {
                        "validation_errors": None,
                        "last_error": None,
                        "last_error_kind": None,
                    })
                    events = harness.complete_task(task_id)
                    await self._persist_task_state(project_id, task_id, harness)
                    await self._persist_project_state(project_id, harness)
                    await event_bus.publish_all(events)
                    self._schedule_ready_tasks(project_id, harness, runner)
                    return

            # Persist the prepared input next to the future output so the
            # IO viewer / agent guidance chat can read what the task was
            # actually told to do (previously the input panel was always
            # blank because io_in_ref was never written).
            await self._save_task_input(project_id, task_id, task_input)

            # Setup task short-circuit (2026-05-19): "create project
            # dirs" is 100% deterministic — output_paths lists every dir,
            # mkdir is idempotent, there is literally nothing for the
            # LLM to reason about. Letting the initializer agent run was
            # producing inconsistent results (proj_39643747047a built
            # 3 of 6 dirs before ReAct max_iter cut it off → validation_
            # failed → user retried 3 times). We just mkdir in Python.
            # Existing emit_output synth below sees kind=='setup' +
            # all paths exist + schema requires file_paths → captures
            # {file_paths: output_paths} → validation passes.
            if (
                task_input.kind == "setup"
                and task_input.output_paths
            ):
                raw_text = await self._fast_path_setup_task(
                    project_id, task_id, task_input,
                )
            else:
                raw_text = await self._run_agent(project_id, task_id, task_input)

            # Prefer emit_output's captured payload if the agent called it.
            # When present, it has already been validated against the
            # task's output_schema inside the tool, so we skip the
            # text-extraction fallback entirely.
            from src.tools.builtin.local._output_capture import pop_output
            captured = pop_output(task_id)

            # Deterministic emit_output synth (2026-05-19): when a
            # single-agent task has PM-decreed output_paths and the
            # agent actually produced every one of them on disk but
            # forgot the closing `emit_output(...)` call, the workflow
            # used to flip to validation_failed("'file_paths' is a
            # required property") even though the real artifacts were
            # already there. file_paths for these tasks is by
            # construction identical to PM's output_paths — synthesise
            # the payload from disk instead of asking the LLM to
            # restate it.
            #
            # Guards (all must hold; otherwise fall through to the
            # normal salvage / validation_failed path):
            #   - captured is None (agent didn't emit)
            #   - performer_kind != "crew" — Crew tasks' captured comes
            #     from the QA step; an empty captured there means QA
            #     itself didn't produce a verdict, which is information
            #     we MUST NOT fabricate. Crew finalize is a separate
            #     work item (#2).
            #   - schema declares file_paths required (so the synth
            #     actually answers the missing field)
            #   - output_paths non-empty
            #   - every listed path exists on disk — this is the
            #     "副作用校验"; without it a half-finished task would
            #     silently flip to done.
            synth_task_row = await crud.get_by_id("tasks", task_id) or {}
            if (
                captured is None
                and synth_task_row.get("performer_kind") != "crew"
                and task_input.output_paths
                and _schema_requires_file_paths(task_input.output_schema)
            ):
                project_row = await crud.get_by_id("projects", project_id) or {}
                project_root_str = project_row.get("root_path") or ""
                if project_root_str:
                    from pathlib import Path
                    root = Path(project_root_str)
                    missing = [
                        p for p in task_input.output_paths
                        if not (root / p).exists()
                    ]
                    if not missing:
                        summary = (
                            f"已建 {len(task_input.output_paths)} 个目录"
                            if task_input.kind == "setup"
                            else f"已产出 {len(task_input.output_paths)} 个文件"
                        )
                        captured = {
                            "file_paths": list(task_input.output_paths),
                            "summary": summary,
                        }
                        log.info("workflow.emit_output_synth",
                                 project_id=project_id, task_id=task_id,
                                 kind=task_input.kind,
                                 n_paths=len(task_input.output_paths))
                    else:
                        log.info("workflow.emit_output_synth_skipped",
                                 project_id=project_id, task_id=task_id,
                                 missing_count=len(missing),
                                 missing_sample=missing[:3])

            if captured is not None:
                extracted = captured if isinstance(captured, dict) else {"value": captured}
                errors = []
            elif task_input.output_schema and task_input.output_schema != {}:
                extracted = await self._extract_structured_output(
                    project_id, task_id, raw_text, task_input.output_schema
                )
                errors = validate_output_schema(extracted, task_input.output_schema)
                # 2026-05-17 salvage: if the agent finished its real work
                # (mkdir / file write / etc.) but forgot to call
                # emit_output, raw_text often summarises what happened
                # without restating the structured fields the schema
                # demands. The generic extraction above sees no JSON in
                # the prose and falls back to `{"_raw": ...}` →
                # validation fails on the missing required keys. Make
                # one more focused LLM pass that ALSO has the task's
                # original instruction in context (so it can derive
                # e.g. file_paths from the directories the agent was
                # told to create). This is a text → JSON translation
                # ONLY — no tools, no side effects, no re-running mkdir.
                if errors:
                    salvaged = await self._salvage_emit_output(
                        task_id, raw_text, task_input,
                    )
                    if salvaged is not None:
                        salvaged_errors = validate_output_schema(
                            salvaged, task_input.output_schema)
                        if not salvaged_errors:
                            log.info("workflow.salvage_recovered",
                                     project_id=project_id, task_id=task_id,
                                     keys=list(salvaged.keys())[:8])
                            extracted = salvaged
                            errors = []
            else:
                extracted = {"_raw": raw_text}
                errors = []

            # V5 Stage B (2026-05-17): if the PM wrote a code_contract
            # for this task, AST-verify (since 2026-05-18) that every
            # .cs file produced actually contains every contracted
            # public symbol. Missing signatures get reported as
            # validation errors so the task moves to validation_failed
            # with concrete "缺少签名 X" messages instead of silently
            # shipping half-implemented code. Non-code tasks have NULL
            # contract → no-op.
            contract_errors = await self._verify_code_contract(
                project_id, task_id,
            )
            # Stage D (2026-05-19): one-shot Debugger patch when EVERY
            # remaining error is a "missing signature" type. Unpatchable
            # errors (file not found, parse failed) skip this path and
            # fall through to validation_failed → user retry. The
            # patch runs once per task per process — repeat triggers
            # need a fresh Crew run (via user retry, which clears the
            # .cs files + drops the attempt flag implicitly).
            if contract_errors and task_id not in self._contract_debugger_attempts:
                patchable = _contract_errors_patchable_by_debugger(
                    contract_errors,
                )
                all_patchable = (
                    patchable
                    and len(patchable) == len(contract_errors)
                )
                if all_patchable:
                    self._contract_debugger_attempts.add(task_id)
                    log.info("contract.debugger_patch_initiated",
                             project_id=project_id, task_id=task_id,
                             n_errors=len(patchable))
                    repair_ran = await self._run_contract_debugger_patch(
                        project_id, task_id, patchable,
                    )
                    if repair_ran:
                        # Re-verify post-patch. If clean → task can
                        # proceed to done; if some errors remain →
                        # normal validation_failed path.
                        contract_errors = await self._verify_code_contract(
                            project_id, task_id,
                        )
                        log.info("contract.debugger_patch_completed",
                                 project_id=project_id, task_id=task_id,
                                 remaining_errors=len(contract_errors))
            if contract_errors:
                errors = list(errors or []) + contract_errors
            # 2026-05-17: render the contract verdict as a synthetic
            # post-QA sub-step so the canvas Crew card has a status
            # indicator for it (without this, the "all sub-cards green
            # but parent red" mismatch confuses users — QA approved,
            # contract caught what QA missed). Only fires when the task
            # actually has a code_contract bound.
            await self._save_contract_check_artifact(
                project_id, task_id, contract_errors,
            )
            # 2026-05-17 P0 verdict gating: an agent that emit_output'd
            # `verdict: 'fail' / 'FAIL' / 'partial_fail' / 'error'` MUST
            # not be allowed to silently pass just because the JSON
            # structure satisfies output_schema. Without this gate, a
            # Crew QA that returned {verdict: 'FAIL', file_paths: []}
            # passed structural validation (file_paths is required, []
            # is a list, schema satisfied) and the parent task moved
            # to DONE — even though QA explicitly said "this failed".
            # The 魔塔副本 audit caught 4/5 Crew QAs in this state.
            verdict_errors = _collect_verdict_errors(extracted)
            if verdict_errors:
                errors = list(errors or []) + verdict_errors

            output = runner.process_output(task_id, raw_text, extracted, errors)

            if output.is_valid:
                if project_id not in self._outputs:
                    self._outputs[project_id] = {}
                self._outputs[project_id][task_id] = output.structured

                await self._save_task_output(project_id, task_id, output)
                # Clear any stale validation_errors / last_error from a
                # prior failed run (retry path) so the UI doesn't show
                # old red noise.
                await crud.update_by_id("tasks", task_id, {
                    "validation_errors": None,
                    "last_error": None,
                    "last_error_kind": None,
                })
                events = harness.complete_task(task_id)
            else:
                # Persist the error list so the UI / retry path / QA agent
                # can show *why* the task failed validation — previously
                # this info evaporated with the WS event.
                #
                # Dedup pass (2026-05-20): errors are appended from up to
                # four sources (schema validator / QA verdict / contract
                # AST verifier / debugger patch attempt) and they often
                # paraphrase the same root cause ("文件不存在" / "Crew
                # Executor 没产出 .cs" / "契约要求 X 不存在" / "缺失符号
                # ..."). Without dedup the canvas tooltip + failure
                # analyser see 4 lines that are really 1. We keep order
                # (first occurrence wins) and collapse exact dupes +
                # near-dupes (one is a substring of another, ignoring
                # punctuation/whitespace).
                err_list = _dedup_errors(output.validation_errors or [])
                await crud.update_by_id("tasks", task_id, {
                    "validation_errors": json.dumps(err_list, ensure_ascii=False),
                    "last_error": "; ".join(err_list)[:500] if err_list else None,
                    "last_error_kind": "validation",
                })
                events = harness.validation_fail_task(task_id, err_list)
                # Auto-diagnosis: spawn the dedicated LLM to write a
                # canonical "原因 + 介入方法" report into tasks.
                # failure_analysis. Fire-and-forget — never blocks task
                # state persistence.
                from agents.failure_analyzer import spawn as spawn_analyzer
                spawn_analyzer(task_id)

            await self._persist_task_state(project_id, task_id, harness)
            await self._persist_project_state(project_id, harness)
            await event_bus.publish_all(events)

            self._schedule_ready_tasks(project_id, harness, runner)

        except Exception as exc:
            err_msg = str(exc)
            kind = _classify_task_error(err_msg)
            log.error("workflow.task_failed",
                      project_id=project_id, task_id=task_id,
                      error=err_msg, kind=kind)
            await crud.update_by_id("tasks", task_id, {
                "last_error": err_msg[:500],
                "last_error_kind": kind,
            })
            events = harness.fail_task(task_id, err_msg)
            # Same auto-diagnosis hook for runtime / exception failures.
            # See validation branch above for rationale.
            from agents.failure_analyzer import spawn as spawn_analyzer
            spawn_analyzer(task_id)
            await self._persist_task_state(project_id, task_id, harness)
            await self._persist_project_state(project_id, harness)
            await event_bus.publish_all(events)
        finally:
            self._run_tasks.pop(key, None)

    async def _maybe_skip_debugger(self, task_input: Any) -> dict | None:
        """Return a synthesised debugger output if final_qa already passed
        (so the LLM call can be skipped), or None if the debugger needs
        to actually run.

        The debugger task depends on final_qa (set up by
        create_workflow._normalize_tasks). We look at the final_qa
        output in the upstream_outputs the runner built — if its
        verdict is "pass", no issues exist to fix.
        """
        for dep_id, dep_output in (task_input.upstream_outputs or {}).items():
            if not isinstance(dep_output, dict):
                continue
            dep_row = await crud.get_by_id("tasks", dep_id)
            if not dep_row or dep_row.get("kind") != "final_qa":
                continue
            if dep_output.get("verdict") == "pass":
                return {
                    "verdict": "fixed",
                    "fixes_applied": [],
                    "issues_escalated": [],
                    "summary": (
                        "final_qa 报告 verdict=pass，没有 issue 需要修复；"
                        "Debugger 自动跳过 LLM 调用。"
                    ),
                }
            break
        return None

    async def _fast_path_setup_task(
        self,
        project_id: str,
        task_id: str,
        task_input: Any,
    ) -> str:
        """Skip the LLM entirely for kind='setup' tasks. Just mkdir all
        listed paths in Python — they are by definition known up front.

        Returns a synthetic raw_text summary so the rest of _execute_task
        (input persistence, output synth, schema validation) flows
        unchanged. The emit_output_synth block downstream picks up
        `kind=='setup'` + paths-exist-on-disk and captures
        {file_paths: output_paths} → schema validation passes.
        """
        from pathlib import Path
        project = await crud.get_by_id("projects", project_id) or {}
        root_str = project.get("root_path") or ""
        if not root_str:
            # No project root → fall back to LLM path (extremely rare;
            # would only hit on a misconfigured project where scaffold
            # somehow finished without setting root_path).
            log.warning("workflow.setup_fast_path_no_root",
                        project_id=project_id, task_id=task_id)
            return await self._run_agent(project_id, task_id, task_input)

        root = Path(root_str)
        created: list[str] = []
        failures: list[tuple[str, str]] = []
        for rel in task_input.output_paths or []:
            try:
                (root / rel).mkdir(parents=True, exist_ok=True)
                created.append(rel)
            except OSError as exc:
                failures.append((rel, str(exc)))

        log.info("workflow.setup_fast_path",
                 project_id=project_id, task_id=task_id,
                 created=len(created), failed=len(failures))
        if failures:
            # If mkdir itself failed (permission / locked / disk full),
            # surface the issue. Downstream existence-check in the synth
            # block will refuse to fake-pass since not all paths exist.
            head = "; ".join(f"{p}: {e}" for p, e in failures[:3])
            return f"mkdir 失败：{head}（已建 {len(created)}/{len(created) + len(failures)}）"
        return f"已建 {len(created)} 个目录（确定性短路，无 LLM）：{', '.join(created[:5])}{'…' if len(created) > 5 else ''}"

    async def _run_agent(self, project_id: str, task_id: str,
                          task_input: Any) -> str:
        """Execute a task — route to Crew runner or single-agent runner.

        PM v4 introduced a performer_kind column on tasks. When the task
        was assigned a Crew (`performer_kind == 'crew'`), the orchestrator
        walks the Crew's agent_sequence step-by-step. Otherwise (v3
        legacy or v4 single-agent picks) the original single-agent path
        runs unchanged.
        """
        task_row = await crud.get_by_id("tasks", task_id) or {}
        performer_kind = task_row.get("performer_kind")

        if performer_kind == "crew":
            performer_id = task_row.get("performer_id")
            if not performer_id:
                raise ValueError(
                    f"Task {task_id} has performer_kind='crew' but no performer_id"
                )
            return await self._run_crew(project_id, task_id, task_input, performer_id)

        agent = await crud.get_by_id("agents", task_input.agent_id)
        if not agent:
            raise ValueError(f"Agent {task_input.agent_id} not found")

        provider_id, model_name = await self._resolve_agent_llm(agent)

        # Try CrewAI first
        try:
            from services.crewai_runner import run_task_with_crewai
            text = await run_task_with_crewai(
                agent_row=agent,
                task_input=task_input,
                provider_id=provider_id,
                model_name=model_name,
                project_id=project_id,
            )
            log.info("workflow.agent_executed_via_crewai",
                     project_id=project_id, task_id=task_id,
                     agent_id=task_input.agent_id)
            return text
        except Exception as exc:
            log.warning("workflow.crewai_failed_falling_back",
                        project_id=project_id, task_id=task_id, error=str(exc))

        # Fallback: direct LLM call (legacy path; loses tool support)
        return await self._run_agent_direct_llm(
            project_id, task_id, task_input, agent, provider_id, model_name,
        )

    async def _run_crew(self, project_id: str, task_id: str,
                         task_input: Any, crew_id: str) -> str:
        """Walk a Crew's agent_sequence head → executors → QA.

        Per Q1 / Q2: each step is its own single-agent kickoff; the
        previous step's emit_output payload is injected into the next
        step's description as structured JSON.

        Per Q7: a pause flag is checked at every step boundary; when set,
        the loop exits cleanly without touching the in-flight CrewAI
        worker (it has already completed the current step).

        Returns a Markdown summary of the full Crew run — workflow_svc's
        existing post-processing will pick up the QA step's structured
        emit_output via `pop_output(task_id)` (the QA step is bound to
        the parent task_id key so the chain's tail flows into the same
        downstream pipeline as a v3 single-agent task).
        """
        from bootstrap.paths import OUTPUT_DIR
        # Imported via this module so tests can monkey-patch it.
        from services import crewai_runner as _crewai_runner

        crew = await crud.get_by_id("crews", crew_id)
        if not crew:
            raise ValueError(f"Crew {crew_id} not found")
        # 2026-05-21 Layer 1: crew_name keys into domain.crew_specs.SPEC_REGISTRY
        # so crewai_runner can wire Task(output_pydantic=Spec) for that
        # (crew_name, step_role) when the provider supports Converter mode.
        crew_name = crew.get("name") or ""
        sequence_raw = crew.get("agent_sequence") or "[]"
        try:
            sequence = json.loads(sequence_raw) if isinstance(sequence_raw, str) else sequence_raw
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"Crew {crew_id} has malformed agent_sequence: {exc}")
        if not isinstance(sequence, list) or not sequence:
            raise ValueError(f"Crew {crew_id} agent_sequence is empty")

        project = await crud.get_by_id("projects", project_id) or {}
        project_root = project.get("root_path") or None

        # output_paths is part of the PM contract; tasks table doesn't
        # have it as a column, but the upstream Plan Maker stores it
        # inside output_schema (as "required" list of path strings) OR
        # in detail. For now derive a best-effort list from output_schema.
        parent_output_schema = task_input.output_schema or {}
        parent_output_paths = _extract_output_paths(parent_output_schema, task_input.detail or "")

        # 2026-05-18: load PM-level code_contract so Crew steps can see
        # the exact public symbols they must implement. Without this the
        # contract was invisible to the Executor agent and only enforced
        # post-Crew by _verify_code_contract — agents routinely missed
        # 3-5 signatures out of 12+ because they couldn't see the list.
        task_row = await crud.get_by_id("tasks", task_id) or {}
        parent_code_contract: dict | None = None
        cc_raw = task_row.get("code_contract")
        if cc_raw:
            try:
                parent_code_contract = (
                    cc_raw if isinstance(cc_raw, dict) else json.loads(cc_raw)
                )
            except (json.JSONDecodeError, TypeError):
                parent_code_contract = None

        sub_dir = OUTPUT_DIR / project_id / task_id / "sub"
        sub_dir.mkdir(parents=True, exist_ok=True)

        # 2026-05-20 image flow v2: PM Phase 7 persists project-level
        # art_style_spec to `.mycrew_pending/art_style.json`. Load it
        # here so the FIRST step of an art Crew (PromptSmith) sees it
        # as part of prev_payload — that step composes per-image
        # subject prompts on top of the project style.
        # `_load_art_style_spec` returns None for code-only projects /
        # legacy projects without Phase 7 output.
        art_style_spec = await self._load_art_style_spec(project_id)
        prev_payload: dict | None = (
            {"art_style_spec": art_style_spec} if art_style_spec else None
        )
        step_summaries: list[str] = []

        for i, step in enumerate(sequence):
            # Q7 soft pause: cooperative check at step boundary
            harness = self._active.get(project_id)
            if harness and harness.state == ProjectState.PAUSED:
                log.info("crew.paused_at_step_boundary",
                         task_id=task_id, step_index=i)
                step_summaries.append(f"⏸ Step {i + 1} skipped — project paused")
                break

            step_role = step.get("role") or "executor"
            step_kind = step.get("kind")  # "script_qa" → deterministic Python QA
            agent_id = step.get("agent_id")
            step_instructions = step.get("step_instructions") or ""
            # Script-QA steps still keep an `agent_id` for UI continuity
            # (the QA Engineer card stays in the team page), but the
            # agent record isn't dispatched — the script runs instead.
            # Missing agent is therefore only fatal for non-script steps.
            agent_row = await crud.get_by_id("agents", agent_id) if agent_id else None
            if not agent_row and step_kind != "script_qa":
                raise ValueError(
                    f"Crew {crew_id} step {i} references missing agent_id {agent_id}"
                )
            agent_label = (agent_row or {}).get("role", "脚本验收")
            provider_id, model_name = (
                await self._resolve_agent_llm(agent_row) if agent_row else (None, None)
            )

            await self._broadcast_sub_step(
                project_id, task_id, i, step_role,
                agent_id, agent_label, "started",
            )

            # ── Script-based QA branch (Stage 2, 2026-05-20) ──────────
            #
            # Replaces LLM QA with deterministic Python checks
            # (`services.qa_script.verify_task_qa`). Same captured shape
            # as an emit_output: {verdict, file_paths, issues, summary}
            # — so the post-Crew pipeline (`pop_output(task_id)` →
            # `_collect_verdict_errors` → schema validation →
            # `_verify_code_contract`) doesn't need to know the QA was
            # scripted vs LLM-driven.
            # ── Script-based Unity asset import branch (Stage 4) ─────
            #
            # Replaces the LLM Technical Artist with deterministic Python
            # rules (file suffix + task.detail keywords → Unity importer
            # settings) calling `manage_asset` via the Unity MCP. Same
            # captured shape as an emit_output — downstream sees a
            # uniform contract. Skips cleanly when project root isn't a
            # Unity project (debug projects, etc.).
            if step_kind == "script_unity_import":
                from services.asset_import_script import import_assets_for_task
                from src.tools.builtin.local._output_capture import set_output

                captured = await import_assets_for_task(
                    task_id=task_id,
                    prev_payload=prev_payload,
                    project_root=project_root or "",
                )
                set_output(task_id, captured)

                synthetic_instructions = (
                    step_instructions
                    or "脚本执行 Unity 资产导入设置（asset_import_script），"
                       "按 suffix 规则映射 importer 字段后调 manage_asset modify。"
                )
                ws_failed = (
                    str(captured.get("verdict", "")).lower() not in _VERDICT_PASS
                )
                await self._save_sub_step_io(
                    project_id, task_id, i, step_role,
                    synthetic_instructions, prev_payload,
                    captured.get("summary") or "TA 脚本完成",
                    captured,
                )
                err_text = None
                if ws_failed and captured.get("issues"):
                    err_text = "; ".join(captured["issues"])[:200]
                await self._broadcast_sub_step(
                    project_id, task_id, i, step_role,
                    agent_id, agent_label,
                    "failed" if ws_failed else "completed",
                    error=err_text,
                )

                prev_payload = captured
                step_summaries.append(
                    f"✓ Step {i + 1}/{len(sequence)} [{step_role} script_unity_import] "
                    f"verdict={captured.get('verdict')} "
                    f"imported={len(captured.get('imported') or [])}"
                )
                continue

            if step_kind == "script_qa":
                from services.qa_script import verify_task_qa
                from src.tools.builtin.local._output_capture import set_output

                # Flatten prev_payload into the list the script expects:
                # fan-out QA receives {results: [...]}, sequential QA
                # receives a single captured dict.
                upstream_results: list[dict] = []
                if isinstance(prev_payload, dict):
                    rs = prev_payload.get("results")
                    if isinstance(rs, list):
                        upstream_results = [r for r in rs if isinstance(r, dict)]
                    else:
                        upstream_results = [prev_payload]

                captured = await verify_task_qa(
                    task_id, captured_results=upstream_results,
                )
                # Bind to the parent task_id key — workflow_svc reads
                # pop_output(task_id) right after _run_crew returns.
                set_output(task_id, captured)

                # Persist sub-step IO so the IO viewer can show what
                # was checked + what failed. Synthesise an
                # "instructions" string explaining the script semantics
                # (better than the empty step_instructions a
                # script-only step might carry).
                synthetic_instructions = (
                    step_instructions
                    or "脚本验收（services.qa_script.verify_task_qa）。"
                       "确定性检查文件存在/尺寸/魔数/契约签名，不调用 LLM。"
                )
                ws_failed = (
                    str(captured.get("verdict", "")).lower() not in _VERDICT_PASS
                )
                summary_line = captured.get("summary") or (
                    "脚本验收完成"
                )
                # Re-use the standard IO writer so the canvas viewer
                # gets identical-shape JSON regardless of LLM vs script
                # provenance.
                await self._save_sub_step_io(
                    project_id, task_id, i, step_role,
                    synthetic_instructions, prev_payload,
                    summary_line, captured,
                )

                err_text = None
                if ws_failed and captured.get("issues"):
                    err_text = "; ".join(captured["issues"])[:200]
                await self._broadcast_sub_step(
                    project_id, task_id, i, step_role,
                    agent_id, agent_label,
                    "failed" if ws_failed else "completed",
                    error=err_text,
                )

                prev_payload = captured
                step_summaries.append(
                    f"✓ Step {i + 1}/{len(sequence)} [{step_role} script] "
                    f"verdict={captured.get('verdict')} "
                    f"issues={len(captured.get('issues') or [])}"
                )
                continue

            # Crew v5 fan-out branch: this step has `fanout` config →
            # dispatch all children of parent_task_id concurrently using
            # the same step.agent + step.instructions, each child bound
            # to its own task_id for emit_output / IO. Returns aggregated
            # {"results": [...]} so the next step (typically QA) sees
            # per-child verdicts.
            #
            # Children-gate (2026-05-20): a Crew sequence may declare
            # `fanout` unconditionally (e.g. 系统实现组 executor), but
            # PM only merges some tasks into a v5 group — leaf tasks
            # using the same crew have zero children. Falling through
            # to _fanout_step in that case returns count=0 and silently
            # skips the step, which lets QA fail "file not produced"
            # for tasks the Executor was supposed to run normally.
            # Pre-check children count and ignore fanout when empty so
            # leaf tasks run the step inline like any non-fanout crew.
            fanout_cfg = step.get("fanout")
            if fanout_cfg:
                _children = await crud.get_all(
                    "tasks", "parent_task_id = ?", (task_id,),
                )
                if not _children:
                    log.info("crew.fanout_skipped_no_children",
                             task_id=task_id, step_index=i,
                             reason="leaf task with fanout config — running step inline")
                    fanout_cfg = None
            if fanout_cfg:
                # 2026-05-20 image flow v2: art_style_spec must reach
                # the Generator (fanout-script) step even though the
                # intermediate Head step (PromptSmith) overwrites
                # prev_payload with its own emit_output. Merge the
                # project-level spec into head_spec at dispatch time
                # so per-child callers (image_gen_script) can read it
                # alongside PromptSmith's per-path prompts.
                fanout_head_spec: dict | None
                if isinstance(prev_payload, dict):
                    fanout_head_spec = dict(prev_payload)
                else:
                    fanout_head_spec = None
                if (
                    art_style_spec
                    and (fanout_head_spec is None
                         or "art_style_spec" not in fanout_head_spec)
                ):
                    if fanout_head_spec is None:
                        fanout_head_spec = {}
                    fanout_head_spec["art_style_spec"] = art_style_spec
                try:
                    captured = await self._fanout_step(
                        project_id=project_id,
                        parent_task_id=task_id,
                        project_root=project_root,
                        step=step, step_index=i, step_role=step_role,
                        agent_row=agent_row,
                        provider_id=provider_id, model_name=model_name,
                        head_spec=fanout_head_spec,
                        concurrency=int(fanout_cfg.get("concurrency_cap") or 1),
                        crew_name=crew_name,
                    )
                except Exception as exc:
                    err = str(exc)
                    log.error("crew.fanout_failed",
                              task_id=task_id, step_index=i, error=err)
                    await self._broadcast_sub_step(
                        project_id, task_id, i, step_role,
                        agent_id, agent_row.get("role", ""), "failed",
                        error=err[:200],
                    )
                    raise
                prev_payload = captured
                step_summaries.append(
                    f"✓ Step {i + 1}/{len(sequence)} [{step_role} fan-out] "
                    f"{agent_row.get('role', '')} — "
                    f"{captured.get('completed', 0)}/{captured.get('count', 0)} ok, "
                    f"{captured.get('failed', 0)} fail"
                )
                await self._broadcast_sub_step(
                    project_id, task_id, i, step_role,
                    agent_id, agent_row.get("role", ""), "completed",
                )
                continue

            try:
                text, captured = await _crewai_runner.run_crew_step_with_crewai(
                    agent_row=agent_row,
                    step_role=step_role,
                    step_index=i,
                    step_instructions=step_instructions,
                    project_id=project_id,
                    project_root=project_root,
                    parent_task_id=task_id,
                    parent_task_title=task_input.title,
                    parent_task_detail=task_input.detail or "",
                    parent_output_schema=parent_output_schema,
                    parent_output_paths=parent_output_paths,
                    parent_code_contract=parent_code_contract,
                    upstream_outputs=task_input.upstream_outputs or {},
                    prev_step_payload=prev_payload,
                    provider_id=provider_id,
                    model_name=model_name,
                    crew_name=crew_name,
                )
            except Exception as exc:
                err = str(exc)
                log.error("crew.step_failed",
                          task_id=task_id, step_index=i, error=err)
                await self._broadcast_sub_step(
                    project_id, task_id, i, step_role,
                    agent_id, agent_row.get("role", ""), "failed",
                    error=err[:200],
                )
                raise

            # 2026-05-17 fix: QA agents sometimes "forget" to call
            # emit_output and instead dump the structured payload as
            # their plain-text final answer. Without rescue, captured
            # stays None → workflow_svc's downstream pop_output fails
            # → fallback _extract_structured_output runs on the Crew's
            # step_summaries markdown (which has no file_paths) →
            # validate_output_schema raises "'file_paths' is a
            # required property" even though the QA agent did produce
            # the right structure. Detected on 魔塔·第一层 / 黄金矿工
            # in production.
            #
            # Heuristic rescue: if a QA step returned no captured but
            # its final-answer text parses as a JSON object, treat
            # that JSON as if it had been emit_output'd. Only for QA
            # — intermediate steps have looser schemas and their
            # raw answers aren't reliably JSON.
            if step_role == "qa" and captured is None and text:
                rescued = _rescue_qa_json(text)
                if rescued is not None:
                    captured = rescued
                    from src.tools.builtin.local._output_capture import set_output
                    set_output(task_id, rescued)
                    log.info("crew.qa_rescued_json",
                             task_id=task_id, step_index=i,
                             keys=list(rescued.keys())[:8])

            # 2026-05-20 chain-of-tools rescue + halt for Head/Executor.
            #
            # Empirically (DeepSeek-v4-flash via CrewAI 1.14), agents
            # occasionally output their `Action: emit_output\nAction
            # Input: {...}` as plain text instead of invoking the tool.
            # CrewAI's ReAct parser sometimes misses the format, leaving
            # captured=None. If we don't rescue + halt here, the next
            # step (Generator) sees prev_payload=None, then runs in
            # empty/loop mode, then TA does the same, then QA finally
            # catches "no file produced" — wasting 3 LLM calls + minutes
            # of wall-clock + token budget.
            #
            # Two-stage handler: (1) try to extract the intended emit_output
            # payload from raw text via _rescue_react_emit_output;
            # (2) if STILL no captured, raise so the Crew halts NOW and
            # the parent task moves to failed with a precise root cause.
            if step_role in ("head", "executor") and captured is None and text:
                rescued = _rescue_react_emit_output(text)
                if rescued is not None:
                    captured = rescued
                    if step_role == "qa":  # belt-and-suspenders, never true here
                        from src.tools.builtin.local._output_capture import set_output
                        set_output(task_id, rescued)
                    log.info("crew.react_emit_rescued",
                             task_id=task_id, step_index=i,
                             role=step_role,
                             keys=list(rescued.keys())[:8])

            # Persist sub-step IO
            await self._save_sub_step_io(
                project_id, task_id, i, step_role,
                step_instructions, prev_payload,
                text, captured,
            )

            # Halt-on-empty (2026-05-20): emit_output was never invoked
            # AND rescue couldn't recover a payload. Downstream cannot
            # function without the spec — stop here with a precise
            # error chain. This closes the Butcher debug case where
            # Head wrote "Action: write_file" instead of emit_output and
            # the whole Crew ran to completion empty-handed.
            #
            # File-existence rescue (2026-05-20 second pass): for
            # Executor steps (not Head — Head's payload is the spec,
            # disk state can't recover that), check if the contract's
            # output_paths are actually on disk + non-empty. The
            # Unity Developer case: agent calls create_script then
            # find_in_file then hits max_iter without ever emit'ing;
            # files exist, only the bookkeeping missed. Treat that as
            # success so the chain doesn't false-fail a completed task.
            if step_role in ("head", "executor") and captured is None:
                if step_role == "executor":
                    # Prefer the task row's output_paths column (the
                    # PM contract authoritative source) over the schema
                    # _extract_output_paths heuristic — they should
                    # agree, but the column is the source of truth.
                    rescue_paths = parent_output_paths
                    if not rescue_paths:
                        try:
                            row = await crud.get_by_id("tasks", task_id) or {}
                            paths_raw = row.get("output_paths")
                            if isinstance(paths_raw, str) and paths_raw:
                                parsed = json.loads(paths_raw)
                                if isinstance(parsed, list):
                                    rescue_paths = [
                                        p for p in parsed if isinstance(p, str)
                                    ]
                            elif isinstance(paths_raw, list):
                                rescue_paths = [
                                    p for p in paths_raw if isinstance(p, str)
                                ]
                        except (json.JSONDecodeError, TypeError, OSError):
                            pass
                    rescued = _rescue_by_file_existence(
                        rescue_paths, project_root,
                    )
                    if rescued is not None:
                        captured = rescued
                        from src.tools.builtin.local._output_capture import set_output
                        set_output(task_id, rescued)
                        log.info(
                            "crew.executor_rescued_by_disk",
                            task_id=task_id, step_index=i,
                            file_count=len(rescued.get("file_paths") or []),
                        )

            if step_role in ("head", "executor") and captured is None:
                # 2026-05-21: classify failure mode + include real LLM
                # output in the error so users don't have to dig into
                # sub/N_*_out.json. Three modes:
                #   A. agent never produced text         (text empty)
                #   B. agent produced unbalanced JSON    (truncated by
                #      max_tokens — LLM cut off mid-string; balanced-
                #      brace rescue can't recover)
                #   C. agent produced something but neither emit_output
                #      tool fired nor a parseable JSON payload appears
                t = text or ""
                if not t.strip():
                    diagnosis = "（agent 没产出任何文本——可能 LLM 调用失败或被框架短路）"
                else:
                    open_braces = t.count("{") - t.count("}")
                    # Truncation tell-tales: ends mid-string (odd number
                    # of unescaped quotes from the last open brace),
                    # ends mid-identifier (no closing delimiter), or
                    # unbalanced braces.
                    likely_truncated = (
                        open_braces > 0
                        or (t.rstrip()[-1:] not in {"}", "]", '"', ".", "。", "”", "*"})
                    )
                    if likely_truncated:
                        diagnosis = (
                            "（agent 产出未闭合的 JSON / 半截文本——很可能"
                            " LLM 触顶 max_tokens 被截断，rescue 无法解析）"
                        )
                    elif "emit_output" in t:
                        diagnosis = (
                            "（raw text 提及 'emit_output' 但格式不被 CrewAI 解析）"
                        )
                    else:
                        diagnosis = "（agent 完全没尝试调用 emit_output）"

                # Include up to 400 chars of head + tail so users see
                # WHAT the agent did. Front matters most (where it
                # started); tail second (where it cut off).
                excerpt_parts: list[str] = []
                if t:
                    excerpt_parts.append(f"head: {t[:300]!r}")
                    if len(t) > 600:
                        excerpt_parts.append(f"tail: {t[-200:]!r}")
                excerpt = " | ".join(excerpt_parts) if excerpt_parts else "(empty)"

                err_msg = (
                    f"Crew {step_role} step {i + 1} 没有调用 emit_output 工具{diagnosis}。"
                    f"下游步骤无法获得 prev_step_payload，终止 Crew。"
                    f"\n实际 LLM 输出 ({len(t)} chars): {excerpt}"
                )
                await self._broadcast_sub_step(
                    project_id, task_id, i, step_role,
                    agent_id, agent_row.get("role", ""), "failed",
                    error=err_msg[:400],
                )
                log.warning(
                    "crew.empty_captured_halt",
                    task_id=task_id, step_index=i, role=step_role,
                    raw_len=len(t),
                    raw_excerpt_head=(t or "")[:200],
                    raw_excerpt_tail=(t or "")[-200:],
                    likely_truncated=("max_tokens 被截断" in diagnosis),
                )
                raise RuntimeError(err_msg)

            # 2026-05-21 Layer 2 server-side disk truth check.
            #
            # When an executor step ships a captured payload with
            # `file_paths`, agent self-report alone is not enough — Probe
            # integration test (diag_layer1_layer2) showed Qwen returns a
            # schema-valid ExecutorOutput WITHOUT actually calling
            # write_file (0/5 trials produced any files). emit_output had
            # this check baked in (emit_output.py:144-185); the Layer 1
            # output_pydantic path bypasses emit_output, so we have to
            # enforce here at the workflow level.
            #
            # Belt-and-suspenders: this also catches the case where
            # legacy emit_output failed to fire (Layer 4b territory) AND
            # the existing rescue layer reconstructed a payload from
            # text — we still verify the files are real.
            #
            # Scope: executor only. Head emits specs (no files). QA
            # verifies disk truth itself + has its own verdict gate, so
            # this check would duplicate.
            if (
                step_role == "executor"
                and isinstance(captured, dict)
                and project_root
            ):
                claimed = captured.get("file_paths") or []
                if isinstance(claimed, list) and claimed:
                    missing_on_disk, zero_byte = _check_claimed_paths_on_disk(
                        claimed, project_root,
                    )
                    if missing_on_disk or zero_byte:
                        parts: list[str] = []
                        if missing_on_disk:
                            parts.append(
                                f"claimed file_paths not on disk: "
                                f"{missing_on_disk[:6]}"
                                + (f" (+{len(missing_on_disk) - 6})"
                                   if len(missing_on_disk) > 6 else "")
                            )
                        if zero_byte:
                            parts.append(
                                f"empty files (failed writes): "
                                f"{zero_byte[:6]}"
                                + (f" (+{len(zero_byte) - 6})"
                                   if len(zero_byte) > 6 else "")
                            )
                        msg = "; ".join(parts)
                        await self._broadcast_sub_step(
                            project_id, task_id, i, step_role,
                            agent_id, agent_row.get("role", ""), "failed",
                            error=msg[:200],
                        )
                        log.warning(
                            "crew.executor_disk_truth_fail",
                            task_id=task_id, step_index=i,
                            missing=missing_on_disk, zero_byte=zero_byte,
                        )
                        raise RuntimeError(
                            f"Crew executor step {i + 1} reported files "
                            f"that don't exist on disk: {msg}"
                        )

            # 2026-05-17 P0 Crew halt: an executor step that emit_output'd
            # verdict='fail' / 'partial_fail' / 'error' means downstream
            # work cannot meaningfully continue — typical case is MCP /
            # ComfyUI unavailable, so the executor produced no real
            # artifacts, but the Crew used to keep marching to QA, which
            # then rubber-stamped pass because the PM contract was empty.
            # Halt here, surface the executor's own issue list to the
            # caller, skip QA entirely. QA's own verdict is handled by
            # workflow_svc's _collect_verdict_errors after the Crew
            # returns (so QA failures don't trigger this halt path —
            # they go through the normal validation_failed flow).
            if step_role in ("head", "executor") and isinstance(captured, dict):
                exec_errors = _collect_verdict_errors(captured)
                if exec_errors:
                    await self._broadcast_sub_step(
                        project_id, task_id, i, step_role,
                        agent_id, agent_row.get("role", ""), "failed",
                        error="; ".join(exec_errors)[:200],
                    )
                    log.warning(
                        "crew.executor_verdict_fail_halt",
                        task_id=task_id, step_index=i, role=step_role,
                        verdict=captured.get("verdict"),
                    )
                    # Raise so _execute_task's outer except branch flips
                    # the parent task to failed with this error chain.
                    # Dedup the verdict-collected issues so the message
                    # doesn't carry 3 paraphrases of the same fact.
                    raise RuntimeError(
                        f"Crew {step_role} step {i + 1} reported "
                        f"verdict='{captured.get('verdict')}': "
                        + "; ".join(_dedup_errors(exec_errors))[:400]
                    )

            prev_payload = captured  # may be None — next step sees null
            step_summaries.append(
                f"✓ Step {i + 1}/{len(sequence)} [{step_role}] {agent_row.get('role', '')} "
                f"— captured={'yes' if captured else 'no'}"
            )

            await self._broadcast_sub_step(
                project_id, task_id, i, step_role,
                agent_id, agent_row.get("role", ""), "completed",
            )

        # The QA step's emit_output was bound to parent task_id, so the
        # caller's `pop_output(task_id)` finds it. We return a markdown
        # log of the Crew run for the agent_output / debug viewers.
        return "\n".join(step_summaries) or "(empty Crew run)"

    async def _load_art_style_spec(self, project_id: str) -> dict | None:
        """Read the project-level art style spec written by PM Phase 7.

        Lives at `<OUTPUT_DIR>/<project_id>/.mycrew_pending/art_style.json`.
        Returns None when:
          - the file doesn't exist (code-only project / pre-Phase-7
            legacy project / Phase 7 LLM failed)
          - the file is malformed JSON
          - the project_id is empty

        Errors are logged + swallowed — the Crew should still be able
        to run on a default style if Phase 7 didn't write anything.
        """
        if not project_id:
            return None
        try:
            from bootstrap.paths import OUTPUT_DIR
            spec_path = (
                OUTPUT_DIR / project_id / ".mycrew_pending" / "art_style.json"
            )
            if not spec_path.exists():
                return None
            raw = spec_path.read_text(encoding="utf-8")
            spec = json.loads(raw)
            if not isinstance(spec, dict):
                log.warning(
                    "workflow.art_style_spec_not_dict",
                    project_id=project_id,
                )
                return None
            return spec
        except json.JSONDecodeError as exc:
            log.warning(
                "workflow.art_style_spec_malformed",
                project_id=project_id, error=str(exc),
            )
            return None
        except OSError as exc:
            log.warning(
                "workflow.art_style_spec_read_failed",
                project_id=project_id, error=str(exc),
            )
            return None

    async def _save_sub_step_io(self, project_id: str, task_id: str,
                                 step_index: int, step_role: str,
                                 step_instructions: str,
                                 prev_payload: dict | None,
                                 raw_text: str,
                                 captured: dict | None) -> None:
        """Write `<OUTPUT_DIR>/<pid>/<tid>/sub/<i>_<role>_{in,out}.json+md`.

        These files back the sub-card IO viewer in the frontend — every
        step gets its own observable slice.
        """
        from bootstrap.paths import OUTPUT_DIR
        sub_dir = OUTPUT_DIR / project_id / task_id / "sub"
        sub_dir.mkdir(parents=True, exist_ok=True)

        in_payload = {
            "step_index": step_index,
            "step_role": step_role,
            "step_instructions": step_instructions,
            "prev_step_payload": prev_payload,
        }
        (sub_dir / f"{step_index}_{step_role}_in.json").write_text(
            json.dumps(in_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # Companion human-readable rendering of the input — the IO
        # viewer's 「输入 · 原始」 panel reads this. Previously only
        # `_out.md` existed, so the viewer's input tab fell back to
        # whatever raw the backend served (which was the OUTPUT md),
        # producing the 2026-05-17 "raw input shows raw output" bug.
        prev_block = (
            json.dumps(prev_payload, ensure_ascii=False, indent=2)
            if prev_payload is not None
            else "(none — this is the first step or upstream emitted nothing)"
        )
        (sub_dir / f"{step_index}_{step_role}_in.md").write_text(
            f"# Step {step_index + 1} · {step_role} · input\n\n"
            f"## Step instructions\n\n```\n{step_instructions[:4000]}\n```\n\n"
            f"## Previous step payload (prev_step_payload)\n\n"
            f"```json\n{prev_block}\n```",
            encoding="utf-8",
        )

        out_payload = {
            "step_index": step_index,
            "step_role": step_role,
            "raw_text": raw_text[:4000],
            "captured": captured,
        }
        (sub_dir / f"{step_index}_{step_role}_out.json").write_text(
            json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (sub_dir / f"{step_index}_{step_role}_out.md").write_text(
            f"# Step {step_index + 1} · {step_role}\n\n"
            f"## Raw text\n\n```\n{raw_text[:4000]}\n```\n\n"
            f"## Captured (emit_output)\n\n```json\n"
            f"{json.dumps(captured, ensure_ascii=False, indent=2) if captured else '(none)'}\n```",
            encoding="utf-8",
        )

    @staticmethod
    def _get_child_code_contract(task_row: dict) -> dict | None:
        """Decode child task's code_contract column (stored as JSON string
        in the DB). Returns the dict or None for non-code tasks."""
        cc_raw = task_row.get("code_contract")
        if isinstance(cc_raw, str) and cc_raw:
            try:
                parsed = json.loads(cc_raw)
                return parsed if isinstance(parsed, dict) else None
            except (json.JSONDecodeError, TypeError):
                return None
        return cc_raw if isinstance(cc_raw, dict) else None

    def _task_input_from_row(self, task_row: dict) -> Any:
        """Build a TaskInput from a raw `tasks` row — used by fan-out
        children which aren't dispatched via TaskRunner.prepare_input."""
        from domain.harness.task_runner import TaskInput
        schema_raw = task_row.get("output_schema")
        if isinstance(schema_raw, str) and schema_raw:
            try:
                schema = json.loads(schema_raw)
            except (json.JSONDecodeError, TypeError):
                schema = {}
        elif isinstance(schema_raw, dict):
            schema = schema_raw
        else:
            schema = {}
        paths_raw = task_row.get("output_paths")
        paths: list[str] | None = None
        if isinstance(paths_raw, str) and paths_raw:
            try:
                parsed = json.loads(paths_raw)
                if isinstance(parsed, list):
                    paths = [p for p in parsed if isinstance(p, str)]
            except (json.JSONDecodeError, TypeError):
                paths = None
        elif isinstance(paths_raw, list):
            paths = [p for p in paths_raw if isinstance(p, str)]
        return TaskInput(
            task_id=task_row["id"],
            title=task_row.get("title", ""),
            detail=task_row.get("detail", "") or "",
            agent_id=task_row.get("agent_id") or "",
            output_schema=schema,
            upstream_outputs={},  # fan-out children inherit parent's spec via head_spec
            kind=task_row.get("kind", "regular"),
            output_paths=paths,
        )

    async def _broadcast_parallel_progress(
        self, *, project_id: str, parent_task_id: str,
        step_index: int, concurrency_cap: int,
        total: int, completed: int, failed: int,
    ) -> None:
        """Fire task.parallel_progress so frontend's ParallelSubCard can
        show x/y progress + running count in real time (UI work in next
        phase). Total / completed / failed are cumulative; running is
        derived = total - completed - failed."""
        try:
            from datetime import datetime, timezone
            from api.ws import manager
            running = max(0, total - completed - failed)
            await manager.broadcast("task.parallel_progress", {
                "parent_task_id": parent_task_id,
                "project_id": project_id,
                "step_index": step_index,
                "concurrency_cap": concurrency_cap,
                "total": total,
                "completed": completed,
                "failed": failed,
                "running": running,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("workflow.parallel_progress_broadcast_failed",
                        parent_task_id=parent_task_id, error=str(exc))

    async def _fanout_step(
        self,
        *,
        project_id: str,
        parent_task_id: str,
        project_root: str | None,
        step: dict,
        step_index: int,
        step_role: str,
        agent_row: dict,
        provider_id: str,
        model_name: str,
        head_spec: Any,
        concurrency: int,
        crew_name: str = "",
    ) -> dict:
        """Fan-out the current Crew step over all children of parent.

        Each child is a `tasks` row with `parent_task_id == parent`. Each
        runs the same step (same agent + step_instructions) but bound to
        the child's own task_id so emit_output / IO land on the child.
        `head_spec` (= prev_payload, the Head step's emit_output) is
        passed to every child as `prev_step_payload` so the Executor
        sees the shared upstream spec.

        Returns aggregated dict {"results": [...], "count", "completed",
        "failed"} so the next step (typically QA) can verdict per-child.
        Per-child IO goes through the standard `_save_task_input/output`
        path — NOT `output/<pid>/<parent>/sub/<i>_*` (those are reserved
        for sequential sub-steps).
        """
        from datetime import datetime, timezone
        from src.tools.builtin.local._output_capture import set_output
        from domain.harness.task_runner import TaskOutput
        from services import crewai_runner as _crewai_runner

        rows = await crud.get_all(
            "tasks", "parent_task_id = ?", (parent_task_id,),
        )
        if not rows:
            log.warning("crew.fanout_no_children",
                        parent_task_id=parent_task_id, step_index=step_index)
            return {"results": [], "count": 0, "completed": 0, "failed": 0}

        # Stamp parent_step_index on every child so the canvas knows
        # which step in the parent's sequence dispatched them.
        for r in rows:
            if r.get("parent_step_index") != step_index:
                await crud.update_by_id("tasks", r["id"], {
                    "parent_step_index": step_index,
                })

        sem = asyncio.Semaphore(max(1, concurrency))
        completed_count = 0
        failed_count = 0
        total = len(rows)

        await self._broadcast_parallel_progress(
            project_id=project_id, parent_task_id=parent_task_id,
            step_index=step_index, concurrency_cap=concurrency,
            total=total, completed=0, failed=0,
        )

        async def _run_child(child: dict) -> dict:
            nonlocal completed_count, failed_count
            child_id = child["id"]
            child_input = self._task_input_from_row(child)
            await self._save_task_input(project_id, child_id, child_input)
            await crud.update_by_id("tasks", child_id, {
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
            })
            try:
                async with sem:
                    if step.get("kind") == "script_comfy_generate":
                        # Stage 3: deterministic ComfyUI HTTP call. Skips
                        # CrewAI / LLM entirely — Head's emit_output
                        # already pinned prompts + dims, the rest is
                        # mechanical (build workflow → POST → poll →
                        # download → resize → save).
                        from services.image_gen_script import (
                            generate_image_for_child,
                        )
                        captured = await generate_image_for_child(
                            child_task_row=child,
                            head_spec=head_spec if isinstance(head_spec, dict) else None,
                            project_root=project_root or "",
                        )
                        text = (
                            f"[script_comfy_generate] {captured.get('summary') or ''}"
                        )
                    else:
                        text, captured = await _crewai_runner.run_crew_step_with_crewai(
                            agent_row=agent_row,
                            step_role=step_role,
                            step_index=step_index,
                            crew_name=crew_name,
                            step_instructions=step.get("step_instructions") or "",
                            project_id=project_id,
                            project_root=project_root,
                            parent_task_id=child_id,  # emit_output binds to CHILD
                            parent_task_title=child_input.title,
                            parent_task_detail=child_input.detail or "",
                            parent_output_schema=child_input.output_schema or {},
                            parent_output_paths=child_input.output_paths or [],
                            parent_code_contract=self._get_child_code_contract(child),
                            upstream_outputs={},
                            prev_step_payload=head_spec,
                            provider_id=provider_id,
                            model_name=model_name,
                        )
            except Exception as exc:  # noqa: BLE001
                failed_count += 1
                err = str(exc)[:500]
                await crud.update_by_id("tasks", child_id, {
                    "status": "failed",
                    "last_error": err,
                    "last_error_kind": "fanout",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                })
                await self._broadcast_parallel_progress(
                    project_id=project_id, parent_task_id=parent_task_id,
                    step_index=step_index, concurrency_cap=concurrency,
                    total=total, completed=completed_count, failed=failed_count,
                )
                log.error("crew.fanout_child_failed",
                          child_task_id=child_id, error=err)
                return {
                    "child_task_id": child_id,
                    "title": child.get("title"),
                    "verdict": "fail",
                    "error": err[:200],
                }

            # Try the ReAct rescue at the child level too — same logic
            # as the sequential head/executor path: agents that dumped
            # `Action: emit_output\nAction Input: {...}` as text get
            # their intended payload recovered before we evaluate.
            structured = captured if isinstance(captured, dict) else None
            if structured is None and text and "emit_output" in text:
                rescued = _rescue_react_emit_output(text)
                if rescued is not None:
                    structured = rescued
                    log.info("crew.fanout_react_emit_rescued",
                             child_task_id=child_id, step_index=step_index,
                             keys=list(rescued.keys())[:8])

            # File-existence rescue for fan-out children (2026-05-20):
            # Unity Developer pattern — create_script wrote the .cs at an
            # earlier ReAct turn, then max_iter cut off before emit_output.
            # Files are on disk + non-empty → treat as success.
            if structured is None:
                child_paths = child_input.output_paths or []
                rescued = _rescue_by_file_existence(child_paths, project_root)
                if rescued is not None:
                    structured = rescued
                    log.info("crew.fanout_child_rescued_by_disk",
                             child_task_id=child_id,
                             file_count=len(rescued.get("file_paths") or []))

            # Persist child output through the standard path. Doing this
            # before the status decision so the IO viewer has the
            # artifacts even on a failed child.
            await self._save_task_output(
                project_id, child_id,
                TaskOutput(task_id=child_id, raw_text=text or "",
                           structured=structured),
            )
            if structured is not None:
                set_output(child_id, structured)

            # Status decision (2026-05-20 fix):
            # A child is failed when EITHER:
            #   (a) emit_output was never invoked + rescue couldn't
            #       recover a payload  → child contributed nothing
            #       usable to the QA aggregate
            #   (b) the agent explicitly self-reported verdict=fail /
            #       partial_fail / error
            #
            # Previously every child was unconditionally marked done,
            # which produced the symptom: 3 children green on the
            # canvas while the parent QA reports "files don't exist".
            # The mis-classification also fooled the canvas fan-out
            # badge (3/3 ok) when reality was 0/3.
            child_verdict_raw = (structured or {}).get("verdict") if structured else None
            child_verdict_norm = (
                str(child_verdict_raw).strip().lower()
                if child_verdict_raw is not None else None
            )
            child_is_pass = (
                structured is not None
                and (
                    child_verdict_norm is None  # no verdict claim = legacy / silent ok
                    or child_verdict_norm in _VERDICT_PASS
                )
            )

            now_iso = datetime.now(timezone.utc).isoformat()
            if child_is_pass:
                await crud.update_by_id("tasks", child_id, {
                    "status": "done",
                    "finished_at": now_iso,
                })
                completed_count += 1
                outcome_verdict = child_verdict_norm or "pass"
                outcome_error: str | None = None
            else:
                # Build a precise error string so the canvas tooltip +
                # failure_analyzer have something useful to show.
                if structured is None:
                    outcome_error = (
                        "child emit_output 未被调用（agent 未真实调用工具，"
                        "raw text 也无可恢复的 emit_output 块）"
                    )
                    last_error_kind = "no_output"
                else:
                    issues = structured.get("issues") or []
                    issue_excerpt = "; ".join(
                        str(x) for x in issues[:3] if x
                    )
                    outcome_error = (
                        f"verdict={child_verdict_raw!r}"
                        + (f"; {issue_excerpt}" if issue_excerpt else "")
                    )
                    last_error_kind = "verdict_fail"
                await crud.update_by_id("tasks", child_id, {
                    "status": "failed",
                    "last_error": outcome_error[:500],
                    "last_error_kind": last_error_kind,
                    "finished_at": now_iso,
                })
                failed_count += 1
                outcome_verdict = "fail"
                log.warning(
                    "crew.fanout_child_marked_failed",
                    child_task_id=child_id, reason=last_error_kind,
                    error=outcome_error[:200],
                )

            await self._broadcast_parallel_progress(
                project_id=project_id, parent_task_id=parent_task_id,
                step_index=step_index, concurrency_cap=concurrency,
                total=total, completed=completed_count, failed=failed_count,
            )
            return {
                "child_task_id": child_id,
                "title": child.get("title"),
                "verdict": outcome_verdict,
                "captured": structured,
                "error": outcome_error,
            }

        results = await asyncio.gather(
            *[_run_child(c) for c in rows],
            return_exceptions=False,
        )
        return {
            "results": results,
            "count": total,
            "completed": completed_count,
            "failed": failed_count,
        }

    async def _broadcast_sub_step(
        self, project_id: str, task_id: str,
        step_index: int, step_role: str,
        agent_id: str | None, agent_role: str,
        status: str, error: str = "",
    ) -> None:
        """Fire a task.sub_step WS event so the Crew sub-cards update live."""
        try:
            from datetime import datetime, timezone
            from api.ws import manager
            payload = {
                "task_id": task_id,
                "project_id": project_id,
                "step_index": step_index,
                "role": step_role,
                "agent_id": agent_id or "",
                "agent_role": agent_role,
                "status": status,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            if error:
                payload["error"] = error
            await manager.broadcast("task.sub_step", payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("workflow.sub_step_broadcast_failed",
                        task_id=task_id, error=str(exc))

    async def _run_agent_direct_llm(
        self,
        project_id: str,
        task_id: str,
        task_input: Any,
        agent: dict,
        provider_id: str,
        model_name: str,
    ) -> str:
        """Direct-LLM fallback when CrewAI can't be used (legacy behaviour)."""
        system_prompt = (
            f"你是一个 AI Agent。\n"
            f"角色: {agent.get('role', 'Assistant')}\n"
            f"目标: {agent.get('goal', '完成分配的任务')}\n"
            f"背景: {agent.get('backstory', '')}\n\n"
            f"请根据任务要求完成工作，输出详细的结果。"
        )

        task_prompt = f"## 任务: {task_input.title}\n\n{task_input.detail}\n"
        if task_input.upstream_outputs:
            task_prompt += "\n## 上游任务输出（供参考）:\n"
            for upstream_id, output in task_input.upstream_outputs.items():
                task_prompt += f"\n### 来自任务 {upstream_id}:\n"
                task_prompt += f"```json\n{json.dumps(output, ensure_ascii=False, indent=2)}\n```\n"

        if task_input.output_schema and task_input.output_schema != {}:
            task_prompt += (
                f"\n## 输出要求:\n"
                f"请确保你的输出能够被提取为以下 JSON Schema 格式:\n"
                f"```json\n{json.dumps(task_input.output_schema, ensure_ascii=False, indent=2)}\n```\n"
            )

        messages = [
            LlmMessage(role="system", content=system_prompt),
            LlmMessage(role="user", content=task_prompt),
        ]
        thinking_mode = bool(agent.get("thinking_mode", 0))

        response = await llm_gateway.chat(
            provider_id, model_name, messages,
            thinking_mode=thinking_mode,
            project_id=project_id,
        )
        log.info("workflow.agent_executed_via_llm",
                 project_id=project_id, task_id=task_id,
                 agent_id=task_input.agent_id,
                 tokens=response.usage.total_tokens)
        return response.text

    async def _salvage_emit_output(
        self, task_id: str, raw_text: str, task_input: Any,
    ) -> dict | None:
        """Last-chance JSON salvage for agents that finished their work
        but forgot to call ``emit_output``. Re-uses the task's own LLM
        for the salvage call, with a prompt that bundles the original
        task instruction so the model can derive fields like
        ``file_paths`` from the directories it was told to create — not
        just from whatever the agent happened to echo back.

        Returns the parsed dict on success, ``None`` if the LLM call
        fails / produces non-JSON. Does NOT re-execute any of the
        agent's tools; this is purely a text → JSON translation pass.
        """
        task = await crud.get_by_id("tasks", task_id)
        agent_id = task.get("agent_id", "") if task else ""
        agent = await crud.get_by_id("agents", agent_id) if agent_id else None
        provider_id, model_name = await self._resolve_agent_llm(agent)

        schema = task_input.output_schema or {}
        salvage_prompt = (
            "上一轮 Agent 完成了任务但忘了调用 emit_output 工具，"
            "导致结构化输出缺失。请基于以下信息重建该 Agent 应该 emit "
            "的 JSON，不要重新执行任何工具或副作用 —— 你的唯一任务是把"
            "已经发生的事实转换成 schema 要求的 JSON。\n\n"
            f"## 任务原始指令（Agent 应该完成的内容）\n{task_input.detail or '(无)'}\n\n"
            f"## Agent 最终输出原文\n{raw_text[:4000]}\n\n"
            f"## 目标 Schema（请严格匹配 required 字段）\n"
            f"```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```\n\n"
            "只输出纯 JSON 对象，不要 markdown、不要解释、不要额外字段。"
            "对于 file_paths 这类字段：列出指令中提到的所有路径"
            "（即便 Agent 输出没逐个回显），保留指令里的相对/绝对路径格式。"
        )
        messages = [
            LlmMessage(role="system",
                       content="你是结构化输出补救助手，只输出纯 JSON。"),
            LlmMessage(role="user", content=salvage_prompt),
        ]
        try:
            response = await llm_gateway.chat(
                provider_id, model_name, messages,
                json_mode=True, temperature=0.1,
            )
            parsed = json.loads(response.text)
            if isinstance(parsed, dict):
                # Also seed _output_capture so any downstream consumer
                # that calls pop_output later (e.g. Crew QA chain) sees
                # the same payload — keeps behaviour symmetric with the
                # happy emit_output path.
                from src.tools.builtin.local._output_capture import set_output
                set_output(task_id, parsed)
                return parsed
        except (json.JSONDecodeError, TypeError, Exception) as exc:
            log.warning("workflow.salvage_failed",
                        task_id=task_id, error=str(exc))
        return None

    async def _extract_structured_output(self, project_id: str, task_id: str,
                                          raw_text: str,
                                          schema: dict) -> dict:
        """Use the task's agent LLM to extract structured output from raw text.

        First tries direct JSON parsing. If that fails, calls LLM with JSON mode
        to extract structured data matching the schema.
        """
        # Try direct JSON parse first
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        # Try extracting JSON block from markdown
        import re
        match = re.search(r"```json\s*\n(.*?)\n```", raw_text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass

        # Fall back to LLM extraction
        task = await crud.get_by_id("tasks", task_id)
        agent_id = task.get("agent_id", "") if task else ""
        agent = await crud.get_by_id("agents", agent_id) if agent_id else None

        provider_id, model_name = await self._resolve_agent_llm(agent)

        extraction_prompt = (
            "从以下文本中提取结构化数据，严格按照给定的 JSON Schema 输出纯 JSON（不要包含 markdown 代码块标记）。\n\n"
            f"## 目标 Schema:\n```json\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## 原始文本:\n{raw_text}\n\n"
            "请输出纯 JSON:"
        )

        messages = [
            LlmMessage(role="system", content="你是一个数据提取助手。只输出纯 JSON，不要任何其他文字。"),
            LlmMessage(role="user", content=extraction_prompt),
        ]

        try:
            response = await llm_gateway.chat(
                provider_id, model_name, messages,
                json_mode=True,
                temperature=0.1,
                project_id=project_id,
            )
            extracted = json.loads(response.text)
            if isinstance(extracted, dict):
                return extracted
        except (json.JSONDecodeError, TypeError, Exception) as exc:
            log.warning("workflow.extraction_failed",
                        task_id=task_id, error=str(exc))

        # Last resort: wrap raw text
        return {"_raw": raw_text}

    async def _resolve_agent_llm(self, agent: dict | None) -> tuple[str, str]:
        """Resolve an agent's LLM to (provider_id, model_name).

        Falls back to default_agent_model from app_settings.
        """
        if agent and agent.get("llm_id"):
            llm_id = agent["llm_id"]
            if ":" in llm_id:
                parts = llm_id.split(":", 1)
                return parts[0], parts[1]
            # Just provider_id
            models = await crud.get_all("llm_models", "provider_id = ?", (llm_id,))
            if models:
                return llm_id, models[0]["model_name"]

        # Fall back to default agent model
        row = await crud.get_all("app_settings", "key = ?", ("default_agent_model",))
        if row and row[0].get("value"):
            val = row[0]["value"]
            if ":" in val:
                parts = val.split(":", 1)
                return parts[0], parts[1]

        # Last fallback: any available provider
        providers = await crud.get_all("llm_providers")
        if providers:
            provider = providers[0]
            models = await crud.get_all("llm_models",
                                         "provider_id = ?", (provider["id"],))
            if models:
                return provider["id"], models[0]["model_name"]

        raise ValueError("未配置任何 LLM，无法执行 Agent 任务")

    # ── Persistence ───────────────────────────────────────

    async def _load_tasks(self, project_id: str) -> list[dict]:
        rows = await crud.get_all("tasks", "project_id = ?", (project_id,))
        result = []
        for r in rows:
            t = dict(r)
            for field in ("deps", "output_schema"):
                if field in t and isinstance(t[field], str):
                    try:
                        t[field] = json.loads(t[field])
                    except (json.JSONDecodeError, TypeError):
                        t[field] = [] if field == "deps" else {}
            result.append(t)
        return result

    async def _persist_project_state(self, project_id: str,
                                      harness: HarnessStateMachine) -> None:
        await crud.update_by_id("projects", project_id, {
            "state": harness.state,
            "is_running": 1 if harness.state == ProjectState.RUNNING else 0,
            "progress_pct": harness.progress_pct,
        })

    async def _persist_task_state(self, project_id: str, task_id: str,
                                   harness: HarnessStateMachine) -> None:
        task = harness.get_task(task_id)
        updates: dict[str, Any] = {"status": task["status"]}
        # Read the previous status off the DB row so we can detect
        # transitions OUT of running (paused / aborted / done / failed)
        # and accumulate runtime onto the project counter. The harness
        # already mutated its in-memory status, so it can't tell us the
        # previous value — the DB still holds it.
        prev_row = await crud.get_by_id("tasks", task_id) or {}
        prev_status = prev_row.get("status")
        now_iso_str = None  # lazily computed below if needed
        if task["status"] == TaskState.RUNNING and not task.get("started_at"):
            from datetime import datetime, timezone
            now_iso_str = datetime.now(timezone.utc).isoformat()
            updates["started_at"] = now_iso_str
            # Seed last_activity_at so the watchdog has a baseline before
            # the first step callback fires.
            updates["last_activity_at"] = now_iso_str
        # All terminal states must stamp finished_at — previously
        # VALIDATION_FAILED was missing, so QA-failed projects looked
        # like they never wrapped up.
        if task["status"] in (
            TaskState.DONE, TaskState.FAILED, TaskState.ABORTED,
            TaskState.VALIDATION_FAILED,
        ):
            from datetime import datetime, timezone
            if now_iso_str is None:
                now_iso_str = datetime.now(timezone.utc).isoformat()
            updates["finished_at"] = now_iso_str
        await crud.update_by_id("tasks", task_id, updates)

        # ── Runtime accumulator (project total_runtime_seconds) ──
        # We split the "stamp open" half (a single column write) from
        # the "close + accumulate" half (which reads-then-updates) so
        # the existing UPDATE above isn't interleaved with metric writes.
        from services import metrics_svc
        # Transition INTO running (from pending / paused / failed retry):
        # open a new interval. The helper is idempotent over the column
        # so re-entering running from a redundant transition is safe.
        if task["status"] == TaskState.RUNNING and prev_status != TaskState.RUNNING:
            await metrics_svc.task_run_started(task_id)
        # Transition OUT of running (paused / done / failed / aborted /
        # validation_failed / blocked): close the interval and add the
        # elapsed seconds to the project. Pause counts as "stop the
        # clock" per the user's spec: "暂停、卡顿、停止不算".
        if (
            prev_status == TaskState.RUNNING
            and task["status"] != TaskState.RUNNING
        ):
            await metrics_svc.task_run_ended(task_id, project_id)

    async def _persist_all_task_states(self, project_id: str,
                                        harness: HarnessStateMachine) -> None:
        for task in harness.get_all_tasks():
            await self._persist_task_state(project_id, task["id"], harness)

    async def _run_contract_debugger_patch(
        self, project_id: str, task_id: str, patchable_errors: list[str],
    ) -> bool:
        """Stage D (2026-05-19): one-shot Debugger pass to fix a small
        set of contract errors (typically: a handful of missing
        signatures in already-written .cs files).

        Strategy: spin the existing seeded Debugger agent with a
        narrowly-scoped step_instructions block that names the missing
        signatures and tells it to add them with script_apply_edits.
        Reuses crewai_runner.run_crew_step_with_crewai (same path the
        normal Crew steps take, just out-of-band step_index so it
        doesn't collide with the parent Crew's step namespace).

        Returns True if the Debugger ran end-to-end and captured an
        emit_output payload — caller should re-run _verify_code_contract
        to see whether the patch actually fixed things. Returns False
        on any setup failure (Debugger not seeded, no project root,
        runtime exception) — caller falls through to validation_failed
        as if the patch attempt had never happened. Never raises.
        """
        try:
            debugger_rows = await crud.get_all(
                "agents", "role = ? AND is_auto_generated = 0",
                ("Debugger",),
            )
            if not debugger_rows:
                log.warning("contract.debugger_not_seeded", task_id=task_id)
                return False
            debugger_row = debugger_rows[0]

            project = await crud.get_by_id("projects", project_id) or {}
            project_root = project.get("root_path") or None
            if not project_root:
                log.info("contract.debugger_skipped_no_root", task_id=task_id)
                return False

            task_row = await crud.get_by_id("tasks", task_id) or {}
            title = task_row.get("title") or ""
            detail = task_row.get("detail") or ""

            def _parse_json(raw: Any, default: Any) -> Any:
                if raw is None:
                    return default
                if isinstance(raw, (dict, list)):
                    return raw
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    return default

            output_schema = _parse_json(task_row.get("output_schema"), {})
            output_paths = _parse_json(task_row.get("output_paths"), [])
            code_contract = _parse_json(task_row.get("code_contract"), None)

            provider_id, model_name = await self._resolve_agent_llm(debugger_row)

            step_instructions = (
                "## 受限契约补丁模式 (Stage D)\n"
                "上游 Crew 已经写出了 .cs 文件，但 PM 代码契约 AST 校验"
                "**仍有缺失签名**。你的任务**精确**且**有界**——"
                "**绝不要重写整个文件**，只补缺少的那几个签名。\n\n"
                "### 你必须做\n"
                "1. 用 read_file_local 读「## 🔴 代码契约」块里**每个** .cs 文件\n"
                "2. 对照下面的错误列表，把**每一个**缺失签名用 "
                "script_apply_edits / apply_text_edits 添加进去：\n"
                "   - 字面照抄契约里的 signature 形态\n"
                "   - 方法体可极简（return 默认值 / // stub 一行注释皆可）\n"
                "   - **不删任何已有代码**、**不改其他签名**、**不重构**\n"
                "3. 全部补完用 find_in_file 自验每条签名都在文件里\n"
                "4. 调 emit_output(payload={'patched_files': [...], "
                "'added_symbols': [...]}) 报告\n\n"
                "### 严禁\n"
                "- 创建新文件\n"
                "- 改其他已存在的方法体\n"
                "- 改业务逻辑\n"
                "- 调 create_script 重写整个 .cs（用 script_apply_edits / "
                "apply_text_edits **增量**修改）\n\n"
                "### 校验器报告的缺失\n"
                + "\n".join(f"- {e}" for e in patchable_errors)
            )

            from services import crewai_runner as _runner
            _text, captured = await _runner.run_crew_step_with_crewai(
                agent_row=debugger_row,
                step_role="executor",
                # Out-of-band step_index so this patch doesn't write
                # into the parent Crew's step slots. Renders as a 99th
                # sub-step JSON file under sub/ — harmless, the canvas
                # ignores sub_step indices beyond the agent_sequence
                # length unless it's the contract sentinel.
                step_index=99,
                step_instructions=step_instructions,
                project_id=project_id,
                project_root=project_root,
                parent_task_id=task_id,
                parent_task_title=title,
                parent_task_detail=detail,
                parent_output_schema=output_schema,
                parent_output_paths=output_paths,
                parent_code_contract=code_contract,
                upstream_outputs={},
                prev_step_payload=None,
                provider_id=provider_id,
                model_name=model_name,
            )
            ran_ok = captured is not None
            log.info("contract.debugger_patch_done",
                     project_id=project_id, task_id=task_id,
                     captured=bool(captured))
            return ran_ok
        except Exception as exc:  # noqa: BLE001
            log.warning("contract.debugger_patch_failed",
                        project_id=project_id, task_id=task_id,
                        error=str(exc))
            return False

    async def _verify_code_contract(
        self, project_id: str, task_id: str,
    ) -> list[str]:
        """V5 Stage B: if tasks.code_contract is non-null for this task,
        regex-check the generated .cs files against the contracted
        signatures. Returns a list of error strings (empty = pass, or
        no contract at all). Never raises — any unexpected exception is
        logged and swallowed so a malformed contract doesn't kill the
        task path.
        """
        try:
            task_row = await crud.get_by_id("tasks", task_id)
            if not task_row:
                return []
            contract_raw = task_row.get("code_contract")
            if not contract_raw:
                return []
            try:
                contract = json.loads(contract_raw)
            except (json.JSONDecodeError, TypeError):
                log.warning("contract_verify.bad_json", task_id=task_id)
                return []
            if not isinstance(contract, dict) or not contract.get("files"):
                return []

            project = await crud.get_by_id("projects", project_id) or {}
            root_str = project.get("root_path") or ""
            if not root_str:
                # No root path means the project hasn't been bound to a
                # filesystem yet — skip rather than false-fail.
                return []
            from pathlib import Path
            project_root = Path(root_str)
            if not project_root.exists():
                return []

            # 2026-05-18 P5 upgrade: switched to AST-based validator
            # (tree-sitter-c-sharp). The legacy regex/substring path
            # had a false-negative on properties whose body style
            # differed from contract literal (`{ get; set; }` vs
            # `{ get => _x; set { ... } }`) — same surface API, code
            # rejected. AST path compares semantic shape (kind + name
            # + type + params + accessors) and is body-style-agnostic.
            # contract_validator.py kept for now as fallback / legacy
            # consumer support but is no longer the hot path here.
            from domain.qa.contract_ast_validator import verify_contract
            return verify_contract(contract, project_root)
        except Exception as exc:  # noqa: BLE001
            log.error("contract_verify.unhandled",
                      task_id=task_id, error=str(exc))
            return []

    async def _save_contract_check_artifact(
        self, project_id: str, task_id: str, contract_errors: list[str],
    ) -> None:
        """Write a synthetic Crew sub-step artifact for the V5 code-
        contract verification. The frontend reads this through the
        existing crew_progress endpoint and renders a small status card
        appended after QA. No-op for tasks without a code_contract.

        File naming follows the existing sub-step convention
        (`<step_index>_<role>_out.json`) so the crew_progress glob picks
        it up automatically; the role is the literal "contract" — a
        reserved sentinel the frontend special-cases.

        step_index is one past the QA step. We resolve it from the
        Crew's agent_sequence length (the QA step is the last entry).
        """
        try:
            task_row = await crud.get_by_id("tasks", task_id)
            if not task_row or not task_row.get("code_contract"):
                return
            performer_id = task_row.get("performer_id")
            if task_row.get("performer_kind") != "crew" or not performer_id:
                return
            crew_row = await crud.get_by_id("crews", performer_id)
            if not crew_row:
                return
            seq_raw = crew_row.get("agent_sequence") or "[]"
            try:
                sequence = json.loads(seq_raw) if isinstance(seq_raw, str) else seq_raw
            except (json.JSONDecodeError, TypeError):
                return
            if not isinstance(sequence, list) or not sequence:
                return
            step_index = len(sequence)  # one past QA

            from bootstrap.paths import OUTPUT_DIR
            sub_dir = OUTPUT_DIR / project_id / task_id / "sub"
            sub_dir.mkdir(parents=True, exist_ok=True)

            passed = not contract_errors
            payload = {
                "step_index": step_index,
                "step_role": "contract",
                "passed": passed,
                "errors": contract_errors,
            }
            (sub_dir / f"{step_index}_contract_out.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Live update so an already-open canvas lights the new card
            # the instant the verification finishes (mirrors the head /
            # executor / qa broadcasts the Crew runner emits per step).
            await self._broadcast_sub_step(
                project_id, task_id, step_index, "contract",
                None, "contract_check",
                "completed" if passed else "failed",
                error="; ".join(contract_errors)[:200] if contract_errors else "",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("contract_artifact_save_failed",
                        task_id=task_id, error=str(exc))

    async def _save_task_input(self, project_id: str, task_id: str,
                                task_input: TaskInput) -> None:
        """Persist the prepared TaskInput so the IO viewer can show it.

        Mirrors _save_task_output: writes `<OUTPUT_DIR>/<pid>/<tid>/in.json`
        + `in.md` and stamps `tasks.io_in_ref` with the JSON path."""
        from bootstrap.paths import OUTPUT_DIR
        task_dir = OUTPUT_DIR / project_id / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "task_id": task_input.task_id,
            "title": task_input.title,
            "detail": task_input.detail,
            "agent_id": task_input.agent_id,
            "kind": task_input.kind,
            "output_schema": task_input.output_schema,
            "upstream_outputs": task_input.upstream_outputs,
        }
        (task_dir / "in.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # Human-readable markdown view of the task brief
        md_lines = [
            f"# Task: {task_input.title}",
            "",
            f"**task_id**: `{task_input.task_id}`  ",
            f"**agent_id**: `{task_input.agent_id}`  ",
            f"**kind**: `{task_input.kind}`",
            "",
            "## 详细指令",
            task_input.detail or "(none)",
            "",
            "## 期望输出 Schema",
            "```json",
            json.dumps(task_input.output_schema, ensure_ascii=False, indent=2),
            "```",
        ]
        if task_input.upstream_outputs:
            md_lines += [
                "",
                "## 上游输出",
                "```json",
                json.dumps(task_input.upstream_outputs, ensure_ascii=False, indent=2),
                "```",
            ]
        (task_dir / "in.md").write_text("\n".join(md_lines), encoding="utf-8")

        await crud.update_by_id("tasks", task_id, {
            "io_in_ref": str(task_dir / "in.json"),
        })

    async def _save_task_output(self, project_id: str, task_id: str,
                                 output: TaskOutput) -> None:
        from bootstrap.paths import OUTPUT_DIR
        task_dir = OUTPUT_DIR / project_id / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        (task_dir / "out.json").write_text(
            json.dumps(output.structured, ensure_ascii=False, indent=2), encoding="utf-8")
        (task_dir / "out.md").write_text(output.raw_text, encoding="utf-8")

        await crud.update_by_id("tasks", task_id, {
            "io_out_ref": str(task_dir / "out.json"),
        })

    # ── Helpers ───────────────────────────────────────────

    def _get_harness(self, project_id: str) -> HarnessStateMachine:
        harness = self._active.get(project_id)
        if not harness:
            raise KeyError(f"Project {project_id} not active")
        return harness

    def _cleanup_project(self, project_id: str) -> None:
        self._active.pop(project_id, None)
        self._runners.pop(project_id, None)
        self._outputs.pop(project_id, None)
        for key in [k for k in self._run_tasks if k.startswith(f"{project_id}:")]:
            task = self._run_tasks.pop(key, None)
            if task:
                task.cancel()
        # Drop the per-project lock too — a stale lock can't deadlock
        # anything (it's project-keyed and the project is now gone) but
        # keeping it around accumulates entries over a long-running
        # process. New start() will allocate a fresh one.
        self._project_locks.pop(project_id, None)

    # ── Project requirement queries ───────────────────────

    async def required_mcps(self, project_id: str) -> list[dict]:
        """List MCP servers this project needs to run.

        2026-05-19 rewrite: was an agent.tool_ids → mcp.discovered_tools
        derivation. That comparison joins on tool NAME, but MyCrew local
        tool names use prefixes (`comfy_*`, `figma_*`, `git_*`) while
        raw MCP `discovered_tools` are unprefixed — so the intersection
        missed every prefixed tool. ComfyUI never showed as required
        (false negative), and Blender showed as required for 2D
        projects (false positive, because Technical Artist happened to
        bind the unprefixed `import_generated_asset`).
        See TEMPLATE_REQUIRED_MCPS docstring in template_cloner_svc.py.

        New rule: look up `project.template_id`, read the hard-coded
        required-MCP whitelist, return the matching mcp_servers rows.
        Legacy projects with no template_id get a derivation fallback
        (returns all enabled MCPs — never block start in that case).

        Returned shape per server:
          { server_id, name, status, tools_used: [], missing_tools: [] }
        `tools_used` / `missing_tools` kept for API compatibility but
        no longer populated (template-driven mode doesn't track per-
        server tool intersection).
        """
        from services.template_cloner_svc import TEMPLATE_REQUIRED_MCPS

        project = await crud.get_by_id("projects", project_id)
        if not project:
            raise KeyError(project_id)
        template_id = project.get("template_id")
        required_names = TEMPLATE_REQUIRED_MCPS.get(template_id)

        from infra.mcp.pool import mcp_pool
        live_status: dict[str, str] = {
            s["server_id"]: s["status"]
            for s in mcp_pool.get_all_statuses()
        }

        servers = await crud.get_all("mcp_servers")
        # Legacy / unknown template → don't block, return empty (UI shows
        # "no required" rather than "everything required").
        if required_names is None:
            log.info("workflow.required_mcps.no_template_whitelist",
                     project_id=project_id, template_id=template_id)
            return []

        required: list[dict] = []
        for s in servers:
            if not s.get("enabled"):
                continue
            if s["name"] not in required_names:
                continue
            required.append({
                "server_id": s["id"],
                "name": s["name"],
                "status": live_status.get(s["id"], "disconnected"),
                "tools_used": [],
                "missing_tools": [],
            })
        # Surface any whitelisted MCPs that don't exist as rows at all
        # (user hasn't added them). Disabled-but-present rows are user
        # intent — don't override that, just let them not appear.
        present_names = {s["name"] for s in servers}
        for missing_name in sorted(required_names - present_names):
            required.append({
                "server_id": "",
                "name": missing_name,
                "status": "not_configured",
                "tools_used": [],
                "missing_tools": [],
            })
        return required


workflow_svc = WorkflowService()
