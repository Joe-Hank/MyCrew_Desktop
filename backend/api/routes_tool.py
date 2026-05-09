from fastapi import APIRouter, HTTPException

from api.schemas import ToolCreate
from services.tool_svc import tool_svc

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def list_tools():
    data = await tool_svc.list_tools()
    return {"ok": True, "data": data}


@router.get("/{tool_id}")
async def get_tool(tool_id: str):
    data = await tool_svc.get_tool(tool_id)
    if not data:
        raise HTTPException(404, detail="tool not found")
    return {"ok": True, "data": data}


@router.post("")
async def create_tool(body: ToolCreate):
    data = await tool_svc.create_tool(body.model_dump())
    return {"ok": True, "data": data}


@router.delete("/{tool_id}")
async def delete_tool(tool_id: str):
    await tool_svc.delete_tool(tool_id)
    return {"ok": True, "data": None}


@router.post("/scan")
async def scan_tools():
    data = await tool_svc.scan_tools_dir()
    return {"ok": True, "data": data}
