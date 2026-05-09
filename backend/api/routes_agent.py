from fastapi import APIRouter, HTTPException

from api.schemas import AgentCreate, AgentUpdate
from services.agent_svc import agent_svc

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents():
    data = await agent_svc.list_agents()
    return {"ok": True, "data": data}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    data = await agent_svc.get_agent(agent_id)
    if not data:
        raise HTTPException(404, detail="agent not found")
    return {"ok": True, "data": data}


@router.post("")
async def create_agent(body: AgentCreate):
    data = await agent_svc.create_agent(body.model_dump())
    return {"ok": True, "data": data}


@router.put("/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate):
    try:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        data = await agent_svc.update_agent(agent_id, updates)
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="agent not found")


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    await agent_svc.delete_agent(agent_id)
    return {"ok": True, "data": None}
