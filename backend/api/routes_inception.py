from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.inception_svc import inception_svc

router = APIRouter(prefix="/inceptions", tags=["inception"])


class SessionCreate(BaseModel):
    llm_id: str
    thinking_mode: bool = False


class SendMessage(BaseModel):
    content: str


class IndexPath(BaseModel):
    path: str


class FinalizeBody(BaseModel):
    blueprint: dict | None = None


@router.get("/sessions")
async def list_sessions():
    data = await inception_svc.list_sessions()
    return {"ok": True, "data": data}


@router.post("/sessions")
async def create_session(body: SessionCreate):
    data = await inception_svc.create_session(body.llm_id, body.thinking_mode)
    return {"ok": True, "data": data}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    data = await inception_svc.get_session(session_id)
    if not data:
        raise HTTPException(404, detail="session not found")
    return {"ok": True, "data": data}


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: SendMessage):
    try:
        data = await inception_svc.send_message(session_id, body.content)
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="session not found")
    except ValueError as exc:
        return {"ok": False, "error": {"code": "llm_error", "message": str(exc)}}


@router.post("/sessions/{session_id}/messages/stream")
async def stream_message(session_id: str, body: SendMessage):
    """Send message and run Plan Maker; final reply is emitted as a single
    inception.message event when ready (no more token streaming in the UI).

    Returns the final result. Any unexpected exception from the Plan Maker /
    legacy-fallback chain is converted to an ok:false envelope so the frontend
    chat queue can surface the error and continue, rather than choking on a
    bare 500.
    """
    try:
        data = await inception_svc.stream_message(session_id, body.content)
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="session not found")
    except ValueError as exc:
        return {"ok": False, "error": {"code": "llm_error", "message": str(exc)}}
    except Exception as exc:  # noqa: BLE001 — final safety net for Plan Maker
        return {"ok": False, "error": {"code": "plan_maker_failed", "message": str(exc)}}


@router.post("/sessions/{session_id}/index")
async def index_path(session_id: str, body: IndexPath):
    try:
        data = await inception_svc.index_path(session_id, body.path)
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="session not found")


@router.post("/sessions/{session_id}/finalize")
async def finalize(session_id: str, body: FinalizeBody):
    try:
        data = await inception_svc.finalize(session_id, body.blueprint)
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="session not found")
    except ValueError as exc:
        return {"ok": False, "error": {"code": "invalid_blueprint", "message": str(exc)}}
