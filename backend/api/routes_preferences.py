"""User UX preferences (read/write KV).

Backs the dismissible-dialog framework — see services/preferences_svc.py.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import preferences_svc

router = APIRouter(prefix="/preferences", tags=["preferences"])


class SetPreferenceBody(BaseModel):
    value: object


@router.get("")
async def list_preferences() -> dict:
    return {"ok": True, "data": await preferences_svc.get_all()}


@router.put("/{key}")
async def upsert_preference(key: str, body: SetPreferenceBody) -> dict:
    try:
        await preferences_svc.set_value(key, body.value)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    return {"ok": True, "data": {"key": key, "value": body.value}}


@router.delete("/{key}")
async def reset_preference(key: str) -> dict:
    removed = await preferences_svc.delete_value(key)
    return {"ok": True, "data": {"key": key, "removed": removed}}
