"""Tap structlog into 3 sinks: rotating file, in-memory ring buffer,
and a WS broadcast channel. Makes the backend log stream visible to
the LogDrawer in real time (otherwise structlog only hits stdout,
which is invisible to packaged users running the backend hidden in
the Tauri sidecar).

Wiring: `bootstrap/main.py` inserts `tap_processor` into the structlog
processor chain *before* the final renderer. The processor never
mutates `event_dict` — it just snapshots + dispatches.

Design notes:
  - File sink uses stdlib TimedRotatingFileHandler (daily rotation,
    14-day retention). One JSON line per record. Survives the process
    so users can post-mortem after a crash.
  - In-memory buffer reuses services.log_svc._buffer (deque maxlen
    2000). Same buffer the GET /logs endpoint reads. Thread-safe.
  - WS broadcast emits `log.line` events. Lazy: skips when the main
    event loop hasn't been bound yet (early startup logs reach file +
    buffer but not WS — acceptable, frontend mount-time replay catches
    them via /logs anyway).
  - Re-entry guard via ContextVar prevents an infinite log → broadcast
    → log loop if anything inside manager.broadcast itself logs.

All side effects swallow their own exceptions: the log pipeline must
never break the calling code.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
from contextvars import ContextVar
from pathlib import Path
from typing import Any


_LOG_FILE_LOGGER: logging.Logger | None = None
_BROADCASTING: ContextVar[bool] = ContextVar(
    "mycrew_log_broadcasting", default=False,
)


def _init_file_logger() -> logging.Logger | None:
    """Lazy-init the rotating file handler on first log. Returns None
    if the LOG_DIR isn't set up yet (very early startup before
    bootstrap.paths.ensure_dirs runs)."""
    global _LOG_FILE_LOGGER
    if _LOG_FILE_LOGGER is not None:
        return _LOG_FILE_LOGGER
    try:
        from bootstrap.paths import LOG_DIR
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.TimedRotatingFileHandler(
            str(LOG_DIR / "mycrew.log"),
            when="midnight",
            backupCount=14,
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("mycrew.file")
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        _LOG_FILE_LOGGER = logger
        return logger
    except Exception:
        return None


def _derive_source(event_name: str) -> str:
    """`mcp.pool.connected` → `mcp`; `workflow.started` → `workflow`;
    bare events without a dot → `app`."""
    if not event_name:
        return "app"
    head = event_name.split(".", 1)[0]
    return head or "app"


def _build_snapshot(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Pull the bits the LogDrawer cares about; copy out so downstream
    consumers can JSON-encode safely without aliasing structlog's
    internal dict."""
    fields = {
        k: v for k, v in event_dict.items()
        if k not in ("timestamp", "level", "event")
    }
    event_name = str(event_dict.get("event", ""))
    return {
        "ts": event_dict.get("timestamp") or "",
        "level": str(event_dict.get("level", "info")),
        "source": _derive_source(event_name),
        "event": event_name,
        "message": event_name,  # LogDrawer uses event name as the headline
        "fields": fields,
        "project_id": fields.get("project_id"),
        "task_id": fields.get("task_id"),
    }


def _to_file(snapshot: dict[str, Any]) -> None:
    fl = _init_file_logger()
    if fl is None:
        return
    try:
        fl.info(json.dumps(snapshot, ensure_ascii=False, default=str))
    except Exception:
        pass  # never break logging


def _to_buffer(snapshot: dict[str, Any]) -> None:
    try:
        from services.log_svc import log_svc
        log_svc._buffer.append(snapshot)
    except Exception:
        pass


def _to_ws(snapshot: dict[str, Any]) -> None:
    """Fire-and-forget broadcast to the WS channel. Skips silently if
    the event loop / manager isn't ready yet (early bootstrap)."""
    if _BROADCASTING.get():
        return  # re-entry guard
    try:
        from infra.runtime import get_main_loop
        from api.ws import manager
        import asyncio
    except Exception:
        return
    loop = get_main_loop()
    if loop is None or loop.is_closed():
        return

    async def _do() -> None:
        token = _BROADCASTING.set(True)
        try:
            await manager.broadcast("log.line", snapshot)
        except Exception:
            pass
        finally:
            try:
                _BROADCASTING.reset(token)
            except Exception:
                pass

    try:
        asyncio.run_coroutine_threadsafe(_do(), loop)
    except Exception:
        pass


def tap_processor(
    _logger: Any, _method_name: str, event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor — placed BEFORE the final renderer so it
    sees the dict already enriched with ts/level/event. Pure
    side-effect; returns event_dict unchanged."""
    try:
        snapshot = _build_snapshot(event_dict)
        _to_file(snapshot)
        _to_buffer(snapshot)
        _to_ws(snapshot)
    except Exception:
        pass  # the structlog chain must never fail
    return event_dict


__all__ = ["tap_processor"]
