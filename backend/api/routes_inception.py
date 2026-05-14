from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.inception_svc import inception_svc

router = APIRouter(prefix="/inceptions", tags=["inception"])


class SessionCreate(BaseModel):
    llm_id: str
    thinking_mode: bool = False
    # Entry-button intent. "create" = 新建项目按钮入口；"iterate" = 已完成
    # 项目卡片上的迭代按钮入口（前端会同时传 parent_project_id 把 root
    # 自动继承到新项目行）
    mode: str = "create"
    parent_project_id: str | None = None
    # Optional: frontend can pre-bake the template pick (drawer-initial
    # ChoicePanel resolves before session create) so the user doesn't
    # have to confirm a template a second time.
    template_id: str | None = None


class SendMessage(BaseModel):
    content: str


class SessionChoice(BaseModel):
    """Structured response to an inception.choices / inception.input_path
    event. Frontend sends one of:
      - {template_id: "unity_2d_urp"} — picked a template
      - {root_path: "F:/UnityProjects/X"} — supplied an iteration root
      - {mode: "create" | "iterate_external"} — picked mode on first turn
    """
    template_id: str | None = None
    root_path: str | None = None
    mode: str | None = None


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
    data = await inception_svc.create_session(
        body.llm_id, body.thinking_mode,
        mode=body.mode, parent_project_id=body.parent_project_id,
        template_id=body.template_id,
    )
    return {"ok": True, "data": data}


@router.post("/sessions/{session_id}/choices")
async def submit_choice(session_id: str, body: SessionChoice):
    """Apply a structured choice (template / root_path / mode) to a session.

    The Inception drawer uses this whenever the user clicks a card or
    confirms a path. After the update we re-broadcast session state so the
    drawer knows it can proceed to the next phase.
    """
    try:
        data = await inception_svc.apply_choice(
            session_id,
            template_id=body.template_id,
            root_path=body.root_path,
            mode=body.mode,
        )
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="session not found")
    except ValueError as exc:
        return {"ok": False, "error": {"code": "invalid_choice", "message": str(exc)}}


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
