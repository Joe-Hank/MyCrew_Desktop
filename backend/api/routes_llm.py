from fastapi import APIRouter, HTTPException

from api.schemas import (
    LlmProviderCreate,
    LlmProviderUpdate,
    LlmModelCreate,
    LlmModelUpdate,
    LlmThinkingProbeRequest,
)
from services.llm_svc import llm_svc

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/providers")
async def list_providers():
    data = await llm_svc.list_providers()
    return {"ok": True, "data": data}


@router.get("/providers/{provider_id}")
async def get_provider(provider_id: str):
    data = await llm_svc.get_provider(provider_id)
    if not data:
        raise HTTPException(404, detail="provider not found")
    return {"ok": True, "data": data}


@router.post("/providers")
async def create_provider(body: LlmProviderCreate):
    data = await llm_svc.create_provider(body.model_dump())
    return {"ok": True, "data": data}


@router.put("/providers/{provider_id}")
async def update_provider(provider_id: str, body: LlmProviderUpdate):
    data = await llm_svc.update_provider(provider_id, body.model_dump(exclude_none=True))
    if not data:
        raise HTTPException(404, detail="provider not found")
    return {"ok": True, "data": data}


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    await llm_svc.delete_provider(provider_id)
    return {"ok": True, "data": None}


@router.post("/models")
async def create_model(body: LlmModelCreate):
    data = await llm_svc.create_model(body.model_dump())
    return {"ok": True, "data": data}


@router.put("/models/{model_id}")
async def update_model(model_id: str, body: LlmModelUpdate):
    data = await llm_svc.update_model(model_id, body.model_dump(exclude_none=True))
    if not data:
        raise HTTPException(404, detail="model not found")
    return {"ok": True, "data": data}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    await llm_svc.delete_model(model_id)
    return {"ok": True, "data": None}


@router.get("/quota")
async def get_quota():
    """Returns cached per-provider quota status (30s TTL)."""
    data = await llm_svc.get_quota()
    return {"ok": True, "data": data}


@router.post("/quota/refresh")
async def refresh_quota():
    """Force a fresh quota probe across all providers (manual refresh button)."""
    data = await llm_svc.get_quota(force=True)
    return {"ok": True, "data": data}


@router.post("/probe-thinking")
async def probe_thinking(body: LlmThinkingProbeRequest):
    """Probe whether a given model supports extended thinking / reasoning.

    Heuristic over (provider_type, model_name) — there is no upstream
    "capabilities" API that answers this question, so the rules are
    baked into the backend. Result is cached on the model row when one
    exists so subsequent reads avoid recomputing.
    """
    if not body.model_id and not (body.provider_id and body.model_name):
        raise HTTPException(
            422,
            detail="provide either model_id, or both provider_id + model_name",
        )
    data = await llm_svc.probe_thinking(
        model_id=body.model_id,
        provider_id=body.provider_id,
        model_name=body.model_name,
    )
    return {"ok": True, "data": data}
