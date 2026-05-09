from fastapi import APIRouter

from api.schemas import ConfigUpdate, PermissionUpdate
from infra.repo import crud
from services.permission_svc import permission_svc

router = APIRouter(tags=["config"])


@router.get("/config")
async def get_config():
    rows = await crud.get_all("app_settings")
    data = {r["key"]: r["value"] for r in rows}
    return {"ok": True, "data": data}


@router.put("/config")
async def update_config(body: ConfigUpdate):
    from infra.repo.sqlite_repo import get_db
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
        (body.key, body.value),
    )
    await db.commit()
    return {"ok": True, "data": {"key": body.key, "value": body.value}}


@router.get("/permissions")
async def get_permissions():
    data = await permission_svc.get_permissions()
    return {"ok": True, "data": data}


@router.put("/permissions")
async def update_permissions(body: list[PermissionUpdate]):
    data = await permission_svc.update_permissions([b.model_dump() for b in body])
    return {"ok": True, "data": data}
