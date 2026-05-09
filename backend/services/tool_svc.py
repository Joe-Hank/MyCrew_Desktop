from __future__ import annotations

import hashlib
import json
from pathlib import Path

import structlog

from infra.repo import crud
from bootstrap.paths import SRC_TOOLS_DIR

log = structlog.get_logger()

JSON_FIELDS = ["params_schema"]


class ToolService:
    async def list_tools(self) -> list[dict]:
        rows = await crud.get_all("tools")
        return [self._decode(r) for r in rows]

    async def get_tool(self, tool_id: str) -> dict | None:
        row = await crud.get_by_id("tools", tool_id)
        return self._decode(row) if row else None

    async def create_tool(self, data: dict) -> dict:
        store = self._encode(data)
        if store.get("script_path"):
            store["checksum"] = self._compute_checksum(store["script_path"])
        row = await crud.insert("tools", store, id_prefix="tool_")
        log.info("tool.created", tool_id=row["id"])
        return self._decode(row)

    async def update_tool(self, tool_id: str, data: dict) -> dict:
        existing = await crud.get_by_id("tools", tool_id)
        if not existing:
            raise KeyError(f"Tool {tool_id} not found")
        store = self._encode(data)
        if store.get("script_path"):
            store["checksum"] = self._compute_checksum(store["script_path"])
        row = await crud.update_by_id("tools", tool_id, store)
        log.info("tool.updated", tool_id=tool_id)
        return self._decode(row)

    async def delete_tool(self, tool_id: str) -> None:
        await crud.delete_by_id("tools", tool_id)
        log.info("tool.deleted", tool_id=tool_id)

    async def scan_tools_dir(self) -> list[dict]:
        results = []
        if not SRC_TOOLS_DIR.exists():
            return results

        for py_file in SRC_TOOLS_DIR.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            rel = py_file.relative_to(SRC_TOOLS_DIR)
            name = rel.stem
            source = "builtin" if "builtin" in str(rel) else "user"
            checksum = self._compute_checksum(str(py_file))

            existing = await crud.get_all(
                "tools", "script_path = ?", (str(py_file),)
            )
            if existing:
                tool = existing[0]
                if tool.get("checksum") != checksum:
                    await crud.update_by_id("tools", tool["id"], {"checksum": checksum})
                    tool["checksum"] = checksum
                    tool["_changed"] = True
                results.append(self._decode(tool))
            else:
                row = await crud.insert("tools", {
                    "name": name,
                    "script_path": str(py_file),
                    "source": source,
                    "checksum": checksum,
                    "params_schema": "{}",
                }, id_prefix="tool_")
                row["_new"] = True
                results.append(self._decode(row))

        log.info("tool.scan_complete", found=len(results))
        return results

    @staticmethod
    def _compute_checksum(path: str) -> str:
        try:
            content = Path(path).read_bytes()
            return hashlib.sha256(content).hexdigest()[:16]
        except OSError:
            return ""

    @staticmethod
    def _encode(data: dict) -> dict:
        out = dict(data)
        for f in JSON_FIELDS:
            if f in out and not isinstance(out[f], str):
                out[f] = json.dumps(out[f])
        return out

    @staticmethod
    def _decode(row: dict) -> dict:
        out = dict(row)
        for f in JSON_FIELDS:
            if f in out and isinstance(out[f], str):
                try:
                    out[f] = json.loads(out[f])
                except (json.JSONDecodeError, TypeError):
                    out[f] = {}
        return out


tool_svc = ToolService()
