"""Project usage metrics — token / cost / runtime accumulators.

Powers the home-page ProjectCard badges:
    "¥0.32 · 12.5k tok"   ← total_input/output_tokens + total_cost_cents
    "1h 23m"              ← total_runtime_seconds

Two phases:
  1. PM phase: usage accumulates onto `inception_sessions.pending_*`
     because no project row exists yet.
  2. Execution phase (post inception_svc.finalize): the pending counts
     are transferred onto the new project row, and every subsequent
     LLM call / runtime interval lands directly on `projects.total_*`.

Cost math: input_price_cny_per_1m / output_price_cny_per_1m are stored
on llm_models as integer cents per 1M tokens (e.g. 1800 = ¥18 / 1M).
Cost in cents is computed as:
    (prompt_tokens * input_price + completion_tokens * output_price) // 1_000_000
Result is rounded *down* — same as the user's intent ("integer fen" to
avoid float drift). Zero-priced models simply contribute 0.

Runtime math: every task transition into/out of `running` toggles
`tasks.last_run_started_at`. The elapsed seconds are added to
`projects.total_runtime_seconds`. Paused/aborted intervals contribute
their partial elapsed; only the wall-clock between a "→ running" and
the next exit-from-running counts. Pauses themselves don't tick.

The PM phase has its own runtime baseline on
`inception_sessions.pm_started_at` — see `pm_phase_started` /
`pm_phase_finished`.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from infra.repo import crud
from infra.repo.sqlite_repo import get_db

log = structlog.get_logger()


# ── Cost calculation (pure) ───────────────────────────────────────


def compute_cost_cents(
    prompt_tokens: int,
    completion_tokens: int,
    input_price_cny_per_1m: int | None,
    output_price_cny_per_1m: int | None,
) -> int:
    """Return cost in integer cents (rounded down).

    Returns 0 when either price column is NULL — that's the "user hasn't
    set a price for this model" signal. Negative token counts (which
    shouldn't happen but adapters sometimes glitch) clamp to zero.
    """
    p_tok = max(0, int(prompt_tokens or 0))
    c_tok = max(0, int(completion_tokens or 0))
    p_price = int(input_price_cny_per_1m or 0)
    c_price = int(output_price_cny_per_1m or 0)
    # cents = (tokens * price_per_1M) / 1_000_000
    return (p_tok * p_price + c_tok * c_price) // 1_000_000


# ── Token / cost recording ────────────────────────────────────────


async def _resolve_model_prices(
    *, provider_id: str | None, model_name: str | None,
) -> tuple[int, int]:
    """Look up (input_price, output_price) for a provider/model pair.

    Returns (0, 0) when no matching row is found — caller still records
    the token count but no cost. We resolve via (provider_id, model_name)
    rather than `models.id` because most call sites carry the human
    model name, not the DB-generated id.
    """
    if not provider_id or not model_name:
        return (0, 0)
    rows = await crud.get_all(
        "llm_models",
        "provider_id = ? AND model_name = ?",
        (provider_id, model_name),
    )
    if not rows:
        return (0, 0)
    row = rows[0]
    return (
        int(row.get("input_price_cny_per_1m") or 0),
        int(row.get("output_price_cny_per_1m") or 0),
    )


async def record_llm_usage(
    *,
    project_id: str | None = None,
    session_id: str | None = None,
    provider_id: str | None,
    model_name: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Add the given token usage onto the right accumulator.

    Pass `project_id` for execution-phase calls, `session_id` for PM-phase
    calls (no project exists yet). When neither is supplied or token
    counts are all-zero, the call is a no-op — keeps the call sites
    boilerplate-free since they always pass whatever they have.

    Failures are swallowed (token tracking must never break the LLM call
    itself), but logged at WARN so they surface in the LogDrawer.
    """
    if not project_id and not session_id:
        return
    p_tok = int(prompt_tokens or 0)
    c_tok = int(completion_tokens or 0)
    if p_tok <= 0 and c_tok <= 0:
        return

    try:
        in_price, out_price = await _resolve_model_prices(
            provider_id=provider_id, model_name=model_name,
        )
        cost = compute_cost_cents(p_tok, c_tok, in_price, out_price)

        db = await get_db()
        if project_id:
            await db.execute(
                "UPDATE projects SET "
                "total_input_tokens = total_input_tokens + ?, "
                "total_output_tokens = total_output_tokens + ?, "
                "total_cost_cents = total_cost_cents + ? "
                "WHERE id = ?",
                (p_tok, c_tok, cost, project_id),
            )
        else:  # session_id (PM phase)
            await db.execute(
                "UPDATE inception_sessions SET "
                "pending_input_tokens = pending_input_tokens + ?, "
                "pending_output_tokens = pending_output_tokens + ?, "
                "pending_cost_cents = pending_cost_cents + ? "
                "WHERE id = ?",
                (p_tok, c_tok, cost, session_id),
            )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "metrics.record_failed",
            project_id=project_id, session_id=session_id,
            model=model_name, error=str(exc),
        )


# ── Runtime tracking — execution phase (tasks) ────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Accept both "Z" suffix and offset-bearing ISO strings — the
        # workflow code stamps with .isoformat() which includes +00:00.
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _elapsed_seconds(start_iso: str | None, end_iso: str | None) -> int:
    """Whole seconds between two ISO timestamps. Clamps to 0 on bad input."""
    start = _parse_iso(start_iso)
    end = _parse_iso(end_iso)
    if not start or not end:
        return 0
    delta = (end - start).total_seconds()
    if delta <= 0:
        return 0
    return int(delta)


async def task_run_started(task_id: str) -> None:
    """Stamp the task's last_run_started_at to "now".

    Called every time a task transitions INTO `running` — including a
    retry after failure. The previous interval (if any) was already
    closed by task_run_ended; if it wasn't (the rare crash-during-run
    case), the orphan reconcile sweep will heal on next start.
    """
    try:
        await crud.update_by_id("tasks", task_id, {
            "last_run_started_at": _now_iso(),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("metrics.task_start_failed", task_id=task_id, error=str(exc))


async def task_run_ended(task_id: str, project_id: str) -> None:
    """Close an open run interval and add the elapsed seconds onto the
    project's runtime counter.

    Idempotent — if `last_run_started_at` is NULL (already closed, or
    never set), the call is a no-op. Also tolerates a NULL project_id
    by silently bailing — keeps the caller code uncluttered for the
    rare orphan task without a project binding.
    """
    if not project_id:
        return
    try:
        task = await crud.get_by_id("tasks", task_id)
        if not task:
            return
        started = task.get("last_run_started_at")
        if not started:
            return
        elapsed = _elapsed_seconds(started, _now_iso())
        await crud.update_by_id("tasks", task_id, {
            "last_run_started_at": None,
        })
        if elapsed <= 0:
            return
        db = await get_db()
        await db.execute(
            "UPDATE projects SET total_runtime_seconds = total_runtime_seconds + ? "
            "WHERE id = ?",
            (elapsed, project_id),
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "metrics.task_end_failed",
            task_id=task_id, project_id=project_id, error=str(exc),
        )


# ── Runtime tracking — PM phase (inception sessions) ──────────────


async def pm_phase_started(session_id: str) -> None:
    """Stamp the PM-phase start marker if one isn't already open.

    Called when Plan Maker begins working on a user message. If the user
    sends two messages back-to-back, the first call sets the marker and
    the second is a no-op (we want a single contiguous interval per LLM
    round, not nested intervals).
    """
    try:
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            return
        if session.get("pm_started_at"):
            return
        await crud.update_by_id("inception_sessions", session_id, {
            "pm_started_at": _now_iso(),
        })
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "metrics.pm_start_failed", session_id=session_id, error=str(exc),
        )


async def pm_phase_finished(session_id: str) -> None:
    """Close an open PM-phase interval and add elapsed seconds to the
    session's pending_runtime_seconds. No-op when pm_started_at is NULL."""
    try:
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            return
        started = session.get("pm_started_at")
        if not started:
            return
        elapsed = _elapsed_seconds(started, _now_iso())
        # Reset marker even when elapsed == 0 so a malformed timestamp
        # doesn't wedge the session in "open" state forever.
        await crud.update_by_id("inception_sessions", session_id, {
            "pm_started_at": None,
        })
        if elapsed <= 0:
            return
        db = await get_db()
        await db.execute(
            "UPDATE inception_sessions SET "
            "pending_runtime_seconds = pending_runtime_seconds + ? "
            "WHERE id = ?",
            (elapsed, session_id),
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "metrics.pm_end_failed", session_id=session_id, error=str(exc),
        )


# ── Transfer on finalize ──────────────────────────────────────────


async def transfer_pending_to_project(session_id: str, project_id: str) -> None:
    """Move a session's pending_* counters onto the project's total_*.

    Called from inception_svc.finalize once the project row has been
    persisted, so PM-phase usage isn't lost when the badges first render.
    Resets the session's pending counters to 0 to prevent double-counting
    if finalize fires twice (defensive — current callers ensure exactly
    one finalize per session).
    """
    try:
        session = await crud.get_by_id("inception_sessions", session_id)
        if not session:
            return
        in_tok = int(session.get("pending_input_tokens") or 0)
        out_tok = int(session.get("pending_output_tokens") or 0)
        cost = int(session.get("pending_cost_cents") or 0)
        rt = int(session.get("pending_runtime_seconds") or 0)
        if in_tok == 0 and out_tok == 0 and cost == 0 and rt == 0:
            return
        db = await get_db()
        await db.execute(
            "UPDATE projects SET "
            "total_input_tokens = total_input_tokens + ?, "
            "total_output_tokens = total_output_tokens + ?, "
            "total_cost_cents = total_cost_cents + ?, "
            "total_runtime_seconds = total_runtime_seconds + ? "
            "WHERE id = ?",
            (in_tok, out_tok, cost, rt, project_id),
        )
        await db.execute(
            "UPDATE inception_sessions SET "
            "pending_input_tokens = 0, pending_output_tokens = 0, "
            "pending_cost_cents = 0, pending_runtime_seconds = 0 "
            "WHERE id = ?",
            (session_id,),
        )
        await db.commit()
        log.info(
            "metrics.pending_transferred",
            session_id=session_id, project_id=project_id,
            tokens=(in_tok + out_tok), cost_cents=cost, runtime_seconds=rt,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "metrics.transfer_failed",
            session_id=session_id, project_id=project_id, error=str(exc),
        )
