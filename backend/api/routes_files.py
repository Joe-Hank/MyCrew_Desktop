"""File indexer endpoint for inception file scanning."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/files", tags=["files"])

MAX_INLINE_BYTES = 200_000
MAX_INLINE_FILES = 50
MAX_READ_BYTES = 200_000


class IndexRequest(BaseModel):
    path: str
    depth: int = 3


class ReadRequest(BaseModel):
    path: str
    max_bytes: int = MAX_READ_BYTES


@router.post("/index")
async def index_path(body: IndexRequest):
    from services.permission_guard import require_permission, PermissionDenied

    try:
        await require_permission("file_read")
    except PermissionDenied as exc:
        return {"ok": False, "error": {"code": "permission_denied", "message": str(exc)}}

    target = Path(body.path)
    if not target.exists():
        raise HTTPException(404, detail="path not found")

    if target.is_file():
        size = target.stat().st_size
        return {"ok": True, "data": {
            "path": str(target),
            "is_dir": False,
            "total_bytes": size,
            "total_files": 1,
            "strategy": "inline" if size <= MAX_INLINE_BYTES else "on_demand",
            "tree": [{"path": str(target), "size": size, "type": "file"}],
        }}

    tree: list[dict] = []
    total_bytes = 0
    total_files = 0

    def scan(p: Path, current_depth: int):
        nonlocal total_bytes, total_files
        if current_depth > body.depth:
            return
        try:
            entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError:
            return

        for entry in entries:
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            if entry.is_dir():
                tree.append({"path": str(entry), "size": 0, "type": "dir"})
                scan(entry, current_depth + 1)
            else:
                size = entry.stat().st_size
                total_bytes += size
                total_files += 1
                tree.append({"path": str(entry), "size": size, "type": "file"})

    scan(target, 1)

    is_small = total_bytes <= MAX_INLINE_BYTES and total_files <= MAX_INLINE_FILES
    strategy = "inline" if is_small else "on_demand"

    return {"ok": True, "data": {
        "path": str(target),
        "is_dir": True,
        "total_bytes": total_bytes,
        "total_files": total_files,
        "strategy": strategy,
        "tree": tree,
    }}


@router.post("/read")
async def read_file(body: ReadRequest):
    from services.permission_guard import require_permission, PermissionDenied

    try:
        await require_permission("file_read")
    except PermissionDenied as exc:
        return {"ok": False, "error": {"code": "permission_denied", "message": str(exc)}}

    target = Path(body.path)
    if not target.exists() or not target.is_file():
        raise HTTPException(404, detail="file not found")

    size = target.stat().st_size
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > body.max_bytes:
            content = content[:body.max_bytes] + "\n... [truncated]"
        return {"ok": True, "data": {
            "path": str(target),
            "size": size,
            "content": content,
            "truncated": size > body.max_bytes,
        }}
    except Exception as exc:
        return {"ok": False, "error": {"code": "read_error", "message": str(exc)}}
