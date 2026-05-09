from __future__ import annotations

import json
import uuid
from typing import Any

from infra.repo.sqlite_repo import get_db


def _gen_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _row_to_dict(row) -> dict[str, Any]:
    return dict(row) if row else {}


def _serialize_json_fields(data: dict, fields: list[str]) -> dict:
    out = dict(data)
    for f in fields:
        if f in out and not isinstance(out[f], str):
            out[f] = json.dumps(out[f])
    return out


def _deserialize_json_fields(data: dict, fields: list[str]) -> dict:
    out = dict(data)
    for f in fields:
        if f in out and isinstance(out[f], str):
            try:
                out[f] = json.loads(out[f])
            except (json.JSONDecodeError, TypeError):
                pass
    return out


async def insert(table: str, data: dict, id_prefix: str = "") -> dict:
    db = await get_db()
    if "id" not in data:
        data["id"] = _gen_id(id_prefix)
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    await db.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    await db.commit()
    return data


async def get_by_id(table: str, row_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def get_all(table: str, where: str = "", params: tuple = ()) -> list[dict]:
    db = await get_db()
    q = f"SELECT * FROM {table}"
    if where:
        q += f" WHERE {where}"
    cursor = await db.execute(q, params)
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def update_by_id(table: str, row_id: str, data: dict) -> dict | None:
    db = await get_db()
    if not data:
        return await get_by_id(table, row_id)
    sets = ", ".join(f"{k} = ?" for k in data.keys())
    values = list(data.values()) + [row_id]
    await db.execute(f"UPDATE {table} SET {sets} WHERE id = ?", values)
    await db.commit()
    return await get_by_id(table, row_id)


async def delete_by_id(table: str, row_id: str) -> bool:
    db = await get_db()
    cursor = await db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    await db.commit()
    return cursor.rowcount > 0


async def count(table: str, where: str = "", params: tuple = ()) -> int:
    db = await get_db()
    q = f"SELECT COUNT(*) FROM {table}"
    if where:
        q += f" WHERE {where}"
    cursor = await db.execute(q, params)
    row = await cursor.fetchone()
    return row[0] if row else 0


async def paginate(
    table: str, page: int = 1, size: int = 4, order_by: str = "created_at DESC",
    where: str = "", params: tuple = (),
) -> dict:
    total = await count(table, where, params)
    offset = (page - 1) * size
    db = await get_db()
    q = f"SELECT * FROM {table}"
    if where:
        q += f" WHERE {where}"
    q += f" ORDER BY {order_by} LIMIT ? OFFSET ?"
    cursor = await db.execute(q, (*params, size, offset))
    rows = await cursor.fetchall()
    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "size": size,
    }
