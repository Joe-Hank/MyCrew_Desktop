"""Storage usage stats — backs the Settings page footer widget."""
from __future__ import annotations

from fastapi import APIRouter

from services.storage_svc import get_storage_usage

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/usage")
async def storage_usage() -> dict:
    data = await get_storage_usage()
    return {"ok": True, "data": data}
