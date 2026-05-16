from __future__ import annotations

import json
import re
import uuid
from typing import Any

from infra.repo.sqlite_repo import get_db


# ── SQL fragment validators (audit 2026-05-16, Top 5 #1) ─────────────
#
# The `table` / `where` / `order_by` arguments below are concatenated
# into the SQL string; the parameter values pass through `?` placeholders
# and are safe. The fragments themselves used to be wholly trusted —
# fine while every caller is in-tree, but one PR away from disaster if
# a route ever interpolated user input. These guards are defence in
# depth, not a substitute for keeping fragments hard-coded.
#
# Strategy: reject obvious injection markers (statement-stackers, comment
# starts, semicolons), enforce a strict identifier shape for table names
# and order_by columns, and verify the `?` placeholder count matches the
# number of supplied params. Existing callers all pass — the helper
# accepts `col = ?`, `col IS NULL`, `col IN ('a','b')` (literal-in-list),
# `col1 = ? AND col2 = ?`, etc.

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Atoms separated by top-level commas for ORDER BY. Three forms accepted:
#   1. Plain identifier: `col` [ASC|DESC]
#   2. Parenthesized boolean expression (the project list uses this to
#      bucket favorited rows above non-favorited):
#        `(favorited_at IS NULL)`, `(col IS NOT NULL)`
#   3. Function call (project list also uses COALESCE for the
#      "newest of two timestamps" tiebreaker):
#        `COALESCE(col1, col2)` [ASC|DESC]
# Combined with the blocklist below this still rejects every known
# SQLi marker; the relaxation only allows characters that have no
# special meaning outside the SELECT clause.
_ORDER_ATOM_RE = re.compile(
    r"""
    ^
    (?:
        # Form 1 — bare column (most common)
        [A-Za-z_][A-Za-z0-9_]*
        |
        # Form 2 — parenthesized IS [NOT] NULL expression
        \(\s*[A-Za-z_][A-Za-z0-9_]*\s+IS(?:\s+NOT)?\s+NULL\s*\)
        |
        # Form 3 — function call with identifier args
        [A-Za-z_][A-Za-z0-9_]*
        \(\s*[A-Za-z_][A-Za-z0-9_]*
          (?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*
        \s*\)
    )
    (?:\s+(?:ASC|DESC))?
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)
# Forbidden substrings in any free-form fragment. Semicolons could
# stack a second statement; `--` and `/*` start comments that hide the
# rest of the SQL; nullbyte aborts parsing on some drivers.
_FRAGMENT_BLOCKLIST = (";", "--", "/*", "*/", "\x00")


class SqlFragmentError(ValueError):
    """Raised when a `table` / `where` / `order_by` argument fails the
    safety check. Surfaces as a 500 to the HTTP caller — never let the
    raw fragment through, even at the cost of breaking a buggy request."""


def _validate_table(table: str) -> None:
    if not isinstance(table, str) or not _IDENTIFIER_RE.match(table):
        raise SqlFragmentError(f"invalid table name: {table!r}")


def _validate_fragment(fragment: str, kind: str) -> None:
    if not isinstance(fragment, str):
        raise SqlFragmentError(f"{kind} must be a string, got {type(fragment).__name__}")
    lower = fragment.lower()
    for bad in _FRAGMENT_BLOCKLIST:
        if bad in lower:
            raise SqlFragmentError(
                f"{kind} contains forbidden substring {bad!r}: {fragment!r}"
            )


def _validate_where(where: str, params: tuple) -> None:
    if not where:
        return
    _validate_fragment(where, "where")
    # Param count check: each '?' must correspond to one positional value.
    expected = where.count("?")
    if expected != len(params):
        raise SqlFragmentError(
            f"where has {expected} placeholders but got {len(params)} params; "
            f"fragment={where!r}"
        )


def _split_top_level_commas(fragment: str) -> list[str]:
    """Split a string on commas that aren't inside parentheses.

    Required for ORDER BY because forms like
    `COALESCE(col1, col2)` contain a comma that belongs to the function
    call, not to the ORDER BY list. A naive split would break the
    function call into two unparseable halves.
    """
    out: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(fragment):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            out.append(fragment[start:i])
            start = i + 1
    out.append(fragment[start:])
    return out


def _validate_order_by(order_by: str) -> None:
    if not order_by:
        return
    _validate_fragment(order_by, "order_by")
    for atom in _split_top_level_commas(order_by):
        atom = atom.strip()
        if not atom:
            continue
        if not _ORDER_ATOM_RE.match(atom):
            raise SqlFragmentError(
                "order_by atom must be a column, a parenthesized "
                "IS [NOT] NULL expression, or a function call with "
                f"identifier args (optionally ASC/DESC). Got {atom!r}"
            )


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
    _validate_table(table)
    # Column names come from data.keys() which is internal — validate
    # the same way as table names so a typo'd / malicious key can't
    # smuggle SQL into the INSERT.
    for col in data.keys():
        if not _IDENTIFIER_RE.match(col):
            raise SqlFragmentError(f"invalid column name: {col!r}")
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
    _validate_table(table)
    db = await get_db()
    cursor = await db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    row = await cursor.fetchone()
    return _row_to_dict(row) if row else None


async def get_all(table: str, where: str = "", params: tuple = ()) -> list[dict]:
    _validate_table(table)
    _validate_where(where, params)
    db = await get_db()
    q = f"SELECT * FROM {table}"
    if where:
        q += f" WHERE {where}"
    cursor = await db.execute(q, params)
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def update_by_id(table: str, row_id: str, data: dict) -> dict | None:
    _validate_table(table)
    for col in data.keys():
        if not _IDENTIFIER_RE.match(col):
            raise SqlFragmentError(f"invalid column name: {col!r}")
    db = await get_db()
    if not data:
        return await get_by_id(table, row_id)
    sets = ", ".join(f"{k} = ?" for k in data.keys())
    values = list(data.values()) + [row_id]
    await db.execute(f"UPDATE {table} SET {sets} WHERE id = ?", values)
    await db.commit()
    return await get_by_id(table, row_id)


async def delete_by_id(table: str, row_id: str) -> bool:
    _validate_table(table)
    db = await get_db()
    cursor = await db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    await db.commit()
    return cursor.rowcount > 0


async def count(table: str, where: str = "", params: tuple = ()) -> int:
    _validate_table(table)
    _validate_where(where, params)
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
    _validate_table(table)
    _validate_where(where, params)
    _validate_order_by(order_by)
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
