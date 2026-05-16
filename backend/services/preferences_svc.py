"""User UX preferences (currently: dismissed-dialog choices).

This is the storage half of the dismissible-dialog framework. When the
frontend shows a confirm dialog with an "不再显示" checkbox and the user
ticks it, the chosen option is stored here under
`dismissed_dialog.<dialog_id>` so the next call to the same dialog can
auto-resolve to that option without prompting.

Keys are namespaced by purpose (`dismissed_dialog.*`, future:
`ui_layout.*`, `default_view.*`) so callers — and any future "reset all
my preferences" action — can target a subset by prefix.

Values are stored as JSON strings; for dismissed-dialog rows the payload
is `{"choice": "<option_value>", "dismissed_at": "<ISO>"}`. The
`updated_at` column duplicates the timestamp as an int epoch so range
queries don't need JSON parsing.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import structlog

from infra.repo import crud
from infra.repo.sqlite_repo import get_db

log = structlog.get_logger()


DISMISSED_DIALOG_PREFIX = "dismissed_dialog."


async def get_all() -> dict[str, Any]:
    """Return every preference as `{key: parsed_value}`.

    The frontend loads this once on app start and keeps it in a React
    Query cache; individual reads use the cache, not another HTTP round
    trip per prompt.
    """
    rows = await crud.get_all("user_preferences")
    out: dict[str, Any] = {}
    for row in rows:
        raw = row.get("value")
        if not isinstance(raw, str):
            continue
        try:
            out[row["key"]] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # Preserve the raw string if it isn't JSON — keeps the row
            # accessible to callers even if a future writer used a
            # different encoding.
            out[row["key"]] = raw
    return out


async def set_value(key: str, value: Any) -> None:
    """Upsert one preference row."""
    if not isinstance(key, str) or not key.strip():
        raise ValueError("preference key must be a non-empty string")
    payload = json.dumps(value, ensure_ascii=False, default=str)
    now = int(time.time())

    db = await get_db()
    existing = await crud.get_all("user_preferences", "key = ?", (key,))
    if existing:
        await db.execute(
            "UPDATE user_preferences SET value = ?, updated_at = ? WHERE key = ?",
            (payload, now, key),
        )
    else:
        await db.execute(
            "INSERT INTO user_preferences (key, value, updated_at) VALUES (?, ?, ?)",
            (key, payload, now),
        )
    await db.commit()


async def delete_value(key: str) -> bool:
    """Drop a single preference row. Returns True if a row was removed."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM user_preferences WHERE key = ?", (key,),
    )
    await db.commit()
    return (cursor.rowcount or 0) > 0


# ── dismissible-dialog helpers ─────────────────────────────────────

def dismissed_dialog_key(dialog_id: str) -> str:
    """Canonical storage key for a dialog's dismissed choice."""
    return f"{DISMISSED_DIALOG_PREFIX}{dialog_id}"


async def set_dismissed_dialog(dialog_id: str, choice: str) -> None:
    """Record that the user opted out of a future dialog, with the choice
    they made this time. Future calls of the same dialog_id should
    auto-resolve to `choice` without prompting."""
    await set_value(
        dismissed_dialog_key(dialog_id),
        {
            "choice": choice,
            "dismissed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    log.info("preferences.dialog_dismissed",
             dialog_id=dialog_id, choice=choice)
