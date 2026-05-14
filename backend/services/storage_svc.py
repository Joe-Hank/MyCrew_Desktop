"""Storage usage statistics — used by the Settings page footer.

"Non-system data" excludes user-config tables (llm_providers, mcp_servers,
permissions, app_settings, tools, agents-where-non-auto, crews) since
those are stable / small and the user is asking "how much of MY work
data is sitting on disk".

Returned breakdown:
  projects_and_tasks   — `projects` + `tasks` table rows
  inception_history    — `inception_sessions` + `inception_messages`
  events_log           — `events` table (audit + WS broadcast log)
  output_files         — `output/` directory recursive byte sum
                         (per-task `out.json` + `out.md` + .mycrew_pending)

Per-table sizes use SQLite's `dbstat` virtual table when available
(precise byte accounting including B-tree overhead); otherwise we fall
back to a heuristic: sum of LENGTH(payload-like-cols) × 1.4 (for index
+ page overhead). The widget is a UX nicety so approximate is fine.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from infra.repo import crud
from bootstrap.paths import OUTPUT_DIR

log = structlog.get_logger()


# Tables whose byte usage we report as "non-system data"
_USER_DATA_TABLES = (
    "projects",
    "tasks",
    "inception_sessions",
    "inception_messages",
    "events",
)


async def _table_bytes_dbstat(table: str) -> int | None:
    """Return precise size via dbstat virtual table; None if unsupported."""
    from infra.repo.sqlite_repo import get_db
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT SUM(payload) FROM dbstat WHERE name = ?", (table,),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        # dbstat may not be compiled in. Caller falls back.
        return None


async def _table_bytes_heuristic(table: str) -> int:
    """Rough size estimate: text columns lengths × 1.4 + 100B per row."""
    from infra.repo.sqlite_repo import get_db
    db = await get_db()
    cursor = await db.execute(f"PRAGMA table_info({table})")
    cols = await cursor.fetchall()
    text_cols = [
        c[1] for c in cols
        if (c[2] or "").upper().startswith(("TEXT", "VARCHAR", "BLOB"))
    ]
    if not text_cols:
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
        n = (await cursor.fetchone())[0] or 0
        return n * 100  # rough constant per-row overhead
    sum_expr = " + ".join(
        f"COALESCE(LENGTH({c}), 0)" for c in text_cols
    )
    cursor = await db.execute(
        f"SELECT COUNT(*), SUM({sum_expr}) FROM {table}"
    )
    row = await cursor.fetchone()
    n = (row[0] or 0)
    text_total = (row[1] or 0)
    return int(text_total * 1.4 + n * 100)


async def _table_bytes(table: str) -> tuple[int, int]:
    """Returns (size_bytes, row_count) for one table."""
    from infra.repo.sqlite_repo import get_db
    db = await get_db()
    cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
    row_count = (await cursor.fetchone())[0] or 0

    size = await _table_bytes_dbstat(table)
    if size is None:
        size = await _table_bytes_heuristic(table)
    return size, row_count


def _walk_dir_bytes(path: Path) -> tuple[int, int]:
    """Sum of all file sizes + total file count under `path`. Missing dir → (0, 0)."""
    if not path.exists() or not path.is_dir():
        return 0, 0
    total_bytes = 0
    file_count = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total_bytes += p.stat().st_size
                    file_count += 1
                except OSError:
                    pass
    except Exception as exc:  # noqa: BLE001
        log.warning("storage.walk_failed", path=str(path), error=str(exc))
    return total_bytes, file_count


async def get_storage_usage() -> dict[str, Any]:
    """Top-level: returns total non-system bytes + per-category breakdown.

    Shape:
      {
        non_system_total_bytes: int,
        breakdown: {
          projects_and_tasks: {bytes, rows}
          inception_history: {bytes, rows}
          events_log: {bytes, rows}
          output_files: {bytes, files}
        },
        notes: "..."
      }
    """
    proj_b, proj_n = await _table_bytes("projects")
    task_b, task_n = await _table_bytes("tasks")
    sess_b, sess_n = await _table_bytes("inception_sessions")
    msg_b, msg_n = await _table_bytes("inception_messages")
    evt_b, evt_n = await _table_bytes("events")

    out_path = Path(OUTPUT_DIR)
    out_b, out_files = _walk_dir_bytes(out_path)

    pt_bytes = proj_b + task_b
    pt_rows = proj_n + task_n
    ih_bytes = sess_b + msg_b
    ih_rows = sess_n + msg_n

    total = pt_bytes + ih_bytes + evt_b + out_b

    return {
        "non_system_total_bytes": total,
        "breakdown": {
            "projects_and_tasks": {"bytes": pt_bytes, "rows": pt_rows},
            "inception_history": {"bytes": ih_bytes, "rows": ih_rows},
            "events_log": {"bytes": evt_b, "rows": evt_n},
            "output_files": {"bytes": out_b, "files": out_files},
        },
        "notes": (
            "Excludes system configuration (llm_providers, mcp_servers, "
            "tools, agents, permissions, app_settings)."
        ),
    }


def format_bytes(n: int) -> str:
    """Human-readable byte size — kept here so frontend has one canonical
    format if it ever calls back for a server-side render."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"
