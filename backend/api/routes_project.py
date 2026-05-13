from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.project_svc import project_svc

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    root_path: str | None = None
    execution_kind: str = "sequential"


class RootPathUpdate(BaseModel):
    root_path: str


class DeleteConfirm(BaseModel):
    name: str


@router.get("")
async def list_projects(page: int = 1, size: int = 4):
    data = await project_svc.list_projects(page=page, size=size)
    return {"ok": True, "data": data}


@router.get("/{project_id}")
async def get_project(project_id: str):
    data = await project_svc.get_project(project_id)
    if not data:
        raise HTTPException(404, detail="project not found")
    return {"ok": True, "data": data}


@router.post("")
async def create_project(body: ProjectCreate):
    data = await project_svc.create_project(body.model_dump())
    return {"ok": True, "data": data}


@router.post("/{project_id}/clone")
async def clone_project(project_id: str):
    try:
        data = await project_svc.clone_project(project_id)
        return {"ok": True, "data": data}
    except KeyError:
        raise HTTPException(404, detail="project not found")


@router.delete("/{project_id}")
async def delete_project(project_id: str, body: DeleteConfirm):
    project = await project_svc.get_project(project_id)
    if not project:
        raise HTTPException(404, detail="project not found")
    if body.name != project["name"]:
        return {"ok": False, "error": {"code": "name_mismatch",
                "message": "Project name does not match"}}
    await project_svc.delete_project(project_id)
    return {"ok": True, "data": None}


@router.put("/{project_id}/root-path")
async def update_root_path(project_id: str, body: RootPathUpdate):
    data = await project_svc.update_root_path(project_id, body.root_path)
    if not data:
        raise HTTPException(404, detail="project not found")
    return {"ok": True, "data": data}


@router.post("/{project_id}/favorite")
async def favorite_project(project_id: str):
    data = await project_svc.favorite(project_id)
    if not data:
        raise HTTPException(404, detail="project not found")
    return {"ok": True, "data": data}


@router.post("/{project_id}/unfavorite")
async def unfavorite_project(project_id: str):
    data = await project_svc.unfavorite(project_id)
    if not data:
        raise HTTPException(404, detail="project not found")
    return {"ok": True, "data": data}
