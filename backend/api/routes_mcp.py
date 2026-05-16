from fastapi import APIRouter, HTTPException

from api.schemas import McpServerCreate, McpServerUpdate, McpToolCall
from services.mcp_svc import mcp_svc
from services.mcp_templates import TEMPLATES, TemplateValidationError

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/templates")
async def list_templates():
    """Return the catalogue of MCP server templates the frontend uses
    to render the create/edit form. Each template carries its field
    schema (label / type / required / placeholder), so the UI doesn't
    need any hard-coded knowledge of figma vs notion vs git.
    """
    return {"ok": True, "data": {"templates": TEMPLATES}}


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
    try:
        data = await mcp_svc.create_server(body.model_dump())
    except TemplateValidationError as exc:
        # Surface field-level errors so the frontend can highlight
        # specific inputs instead of showing a generic "save failed".
        return {
            "ok": False,
            "error": {
                "code": "template_validation",
                "message": str(exc),
                "field_errors": [
                    {"field": k, "message": m} for k, m in exc.errors
                ],
            },
        }
    return {"ok": True, "data": data}


@router.put("/servers/{server_id}")
async def update_server(server_id: str, body: McpServerUpdate):
    try:
        data = await mcp_svc.update_server(
            server_id, body.model_dump(exclude_none=True),
        )
    except TemplateValidationError as exc:
        return {
            "ok": False,
            "error": {
                "code": "template_validation",
                "message": str(exc),
                "field_errors": [
                    {"field": k, "message": m} for k, m in exc.errors
                ],
            },
        }
    if not data:
        raise HTTPException(404, detail="server not found")
    return {"ok": True, "data": data}


@router.delete("/servers/{server_id}")
async def delete_server(server_id: str):
    await mcp_svc.delete_server(server_id)
    return {"ok": True, "data": None}


@router.post("/servers/{server_id}/connect")
async def connect_server(server_id: str):
    try:
        data = await mcp_svc.connect_server(server_id)
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="server not found")
    except Exception as exc:
        return {"ok": False, "error": {"code": "connect_failed", "message": str(exc)}}


@router.post("/servers/{server_id}/disconnect")
async def disconnect_server(server_id: str):
    await mcp_svc.disconnect_server(server_id)
    return {"ok": True, "data": None}


@router.post("/servers/{server_id}/restart")
async def restart_server(server_id: str):
    try:
        data = await mcp_svc.restart_server(server_id)
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="server not found")
    except Exception as exc:
        return {"ok": False, "error": {"code": "restart_failed", "message": str(exc)}}


@router.post("/refresh-all")
async def refresh_all():
    data = await mcp_svc.refresh_all()
    return {"ok": True, "data": data}


@router.get("/status")
async def mcp_status():
    data = await mcp_svc.get_status_summary()
    return {"ok": True, "data": data}


@router.post("/internal/call")
async def internal_call(body: McpToolCall):
    """Loopback endpoint for BaseTool wrappers to call MCP tools."""
    from services.permission_guard import check_tool_permissions, PermissionDenied

    try:
        # Check permissions before executing the tool
        await check_tool_permissions(body.tool_name, body.arguments)
        result = await mcp_svc.call_tool(body.server_id, body.tool_name, body.arguments)
        return {"ok": True, "data": {"result": result}}
    except PermissionDenied as exc:
        return {"ok": False, "error": {"code": "permission_denied", "message": str(exc)}}
    except KeyError:
        raise HTTPException(404, detail="server not in pool")
    except Exception as exc:
        return {"ok": False, "error": {"code": "call_failed", "message": str(exc)}}
