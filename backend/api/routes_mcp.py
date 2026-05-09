from fastapi import APIRouter, HTTPException

from api.schemas import McpServerCreate, McpServerUpdate
from services.mcp_svc import mcp_svc

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/servers")
async def list_servers():
    data = await mcp_svc.list_servers()
    return {"ok": True, "data": data}


@router.get("/servers/{server_id}")
async def get_server(server_id: str):
    data = await mcp_svc.get_server(server_id)
    if not data:
        raise HTTPException(404, detail="server not found")
    return {"ok": True, "data": data}


@router.post("/servers")
async def create_server(body: McpServerCreate):
    data = await mcp_svc.create_server(body.model_dump())
    return {"ok": True, "data": data}


@router.put("/servers/{server_id}")
async def update_server(server_id: str, body: McpServerUpdate):
    data = await mcp_svc.update_server(server_id, body.model_dump(exclude_none=True))
    if not data:
        raise HTTPException(404, detail="server not found")
    return {"ok": True, "data": data}


@router.delete("/servers/{server_id}")
async def delete_server(server_id: str):
    await mcp_svc.delete_server(server_id)
    return {"ok": True, "data": None}


@router.post("/servers/{server_id}/restart")
async def restart_server(server_id: str):
    return {"ok": True, "data": {"message": "restart not implemented yet"}}


@router.post("/refresh-all")
async def refresh_all():
    data = await mcp_svc.refresh_all()
    return {"ok": True, "data": data}


@router.get("/status")
async def mcp_status():
    data = await mcp_svc.get_status_summary()
    return {"ok": True, "data": data}
