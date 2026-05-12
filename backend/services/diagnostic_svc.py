"""Diagnostic bundle export — plan §17.5.

One-click ZIP containing:
- recent logs (last 5000 entries from `logs` table + in-memory buffer)
- redacted configs (api_key_ref → masked)
- system info (Python version, OS, deps)
- last_state.json if present
"""
from __future__ import annotations

import io
import json
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import structlog

from bootstrap.paths import LAST_STATE_PATH, OUTPUT_DIR
from infra.repo import crud
from services.log_svc import log_svc

log = structlog.get_logger()


def _mask_secret(value: str | None) -> str:
    """Return a masked version of an API key string."""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}...{value[-4:]}"


async def _collect_configs() -> dict:
    """Pull configs from DB with secrets redacted."""
    providers = await crud.get_all("llm_providers")
    for p in providers:
        if "api_key_ref" in p:
            p["api_key_ref"] = _mask_secret(p["api_key_ref"])

    return {
        "llm_providers": providers,
        "llm_models": await crud.get_all("llm_models"),
        "mcp_servers": await crud.get_all("mcp_servers"),
        "agents": await crud.get_all("agents"),
        "crews": await crud.get_all("crews"),
        "tools": await crud.get_all("tools"),
        "projects": await crud.get_all("projects"),
    }


def _collect_system_info() -> dict:
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


async def export_diagnostic_bundle(output_path: Path | None = None) -> Path:
    """Build a zip diagnostic bundle and return its path."""
    if output_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        output_path = OUTPUT_DIR / f"diagnostic-{ts}.zip"

    configs = await _collect_configs()
    system = _collect_system_info()
    recent_logs = await log_svc.query(limit=5000)
    buffer = log_svc.get_buffer_snapshot()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("system.json", json.dumps(system, ensure_ascii=False, indent=2))
        zf.writestr("configs.json", json.dumps(configs, ensure_ascii=False, indent=2, default=str))
        zf.writestr("logs.json", json.dumps(recent_logs, ensure_ascii=False, indent=2, default=str))
        zf.writestr("tail_buffer.json", json.dumps(buffer, ensure_ascii=False, indent=2, default=str))

        if LAST_STATE_PATH.exists():
            zf.write(LAST_STATE_PATH, arcname="last_state.json")

    output_path.write_bytes(buf.getvalue())
    log.info("diagnostic.exported", path=str(output_path), size_bytes=output_path.stat().st_size)
    return output_path
