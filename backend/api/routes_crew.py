from fastapi import APIRouter, HTTPException

from api.schemas import CrewCreate, CrewUpdate
from services.crew_svc import crew_svc

router = APIRouter(prefix="/crews", tags=["crews"])


@router.get("")
async def list_crews():
    data = await crew_svc.list_crews()
    return {"ok": True, "data": data}


@router.get("/{crew_id}")
async def get_crew(crew_id: str):
    data = await crew_svc.get_crew(crew_id)
    if not data:
        raise HTTPException(404, detail="crew not found")
    return {"ok": True, "data": data}


@router.post("")
async def create_crew(body: CrewCreate):
    data = await crew_svc.create_crew(body.model_dump())
    return {"ok": True, "data": data}


@router.put("/{crew_id}")
async def update_crew(crew_id: str, body: CrewUpdate):
    try:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        data = await crew_svc.update_crew(crew_id, updates)
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="crew not found")


@router.delete("/{crew_id}")
async def delete_crew(crew_id: str):
    await crew_svc.delete_crew(crew_id)
    return {"ok": True, "data": None}
