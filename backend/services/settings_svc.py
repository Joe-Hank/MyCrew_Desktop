"""App-level settings stored in the `app_settings` key/value table.

Currently exposes:
  - compliance_mode (free | harmonious)

Add new keys here as the app grows. Each setting gets its own pair of
get/set functions (no generic API exposed to clients) so we can enforce
allowed values at the boundary.
"""
from __future__ import annotations

from typing import Literal

import structlog

from infra.repo import crud
from infra.repo.sqlite_repo import get_db

log = structlog.get_logger()


ComplianceMode = Literal["free", "harmonious"]
_COMPLIANCE_DEFAULT: ComplianceMode = "free"
_COMPLIANCE_VALUES: set[str] = {"free", "harmonious"}


async def _get_setting(key: str, default: str) -> str:
    rows = await crud.get_all("app_settings", "key = ?", (key,))
    if rows:
        return str(rows[0].get("value") or default)
    return default


async def _set_setting(key: str, value: str) -> None:
    """Upsert a single app_settings row."""
    db = await get_db()
    rows = await crud.get_all("app_settings", "key = ?", (key,))
    if rows:
        await db.execute(
            "UPDATE app_settings SET value = ? WHERE key = ?",
            (value, key),
        )
    else:
        await db.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    await db.commit()


# ── compliance_mode ────────────────────────────────────────────────

async def get_compliance_mode() -> ComplianceMode:
    """Return 'free' or 'harmonious'. Defaults to 'free' if unset (per spec)."""
    raw = await _get_setting("compliance_mode", _COMPLIANCE_DEFAULT)
    if raw in _COMPLIANCE_VALUES:
        return raw  # type: ignore[return-value]
    log.warning("settings.compliance_mode_invalid",
                stored=raw, fallback=_COMPLIANCE_DEFAULT)
    return _COMPLIANCE_DEFAULT


async def set_compliance_mode(mode: ComplianceMode) -> None:
    """Persist the user's mode choice. Raises ValueError on unknown value."""
    if mode not in _COMPLIANCE_VALUES:
        raise ValueError(
            f"compliance_mode must be one of {sorted(_COMPLIANCE_VALUES)}, got {mode!r}"
        )
    await _set_setting("compliance_mode", mode)
    log.info("settings.compliance_mode_set", mode=mode)
