"""App-level settings API (compliance_mode for now).

Distinct from `routes_config.py` (per-LLM/MCP/permission config). This is
a top-level singleton settings surface — currently just compliance_mode.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.settings_svc import (
    get_compliance_mode,
    set_compliance_mode,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class ComplianceModeBody(BaseModel):
    mode: str  # "free" | "harmonious"


@router.get("/compliance-mode")
async def read_compliance_mode() -> dict:
    return {"ok": True, "data": {"mode": await get_compliance_mode()}}


@router.put("/compliance-mode")
async def write_compliance_mode(body: ComplianceModeBody) -> dict:
    try:
        await set_compliance_mode(body.mode)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    return {"ok": True, "data": {"mode": body.mode}}
