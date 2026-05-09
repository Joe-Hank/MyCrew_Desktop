from fastapi import APIRouter, HTTPException

from api.schemas import LlmProviderCreate, LlmProviderUpdate, LlmModelCreate, LlmModelUpdate
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
    data = await llm_svc.get_quota()
    return {"ok": True, "data": data}
