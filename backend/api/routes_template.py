"""Read-only catalog of Unity templates used by Plan Maker creation mode.

Frontend pulls this at inception time to render the template-pick step.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from data.unity_templates import get_template, list_templates

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("")
async def list_all_templates() -> dict:
    return {"ok": True, "data": list_templates()}


@router.get("/{template_id}")
async def get_one_template(template_id: str) -> dict:
    t = get_template(template_id)
    if not t:
        raise HTTPException(404, detail=f"template {template_id} not found")
    return {"ok": True, "data": t}
