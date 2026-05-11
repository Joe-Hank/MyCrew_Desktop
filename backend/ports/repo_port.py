"""Repo Port — abstract interface for data persistence (dependency inversion)."""
from __future__ import annotations

from typing import Any, Protocol


class RepoPort(Protocol):
    """Abstract CRUD interface for persistent storage.

    Domain and service layers depend on this protocol, not on the
    concrete SQLite implementation in ``infra.repo``.
    """

    async def insert(self, table: str, data: dict[str, Any],
                     id_prefix: str = "") -> dict[str, Any]: ...

    async def get_by_id(self, table: str, row_id: str) -> dict[str, Any] | None: ...

    async def get_all(self, table: str, where: str = "",
                      params: tuple = ()) -> list[dict[str, Any]]: ...

    async def update_by_id(self, table: str, row_id: str,
                           data: dict[str, Any]) -> dict[str, Any] | None: ...

    async def delete_by_id(self, table: str, row_id: str) -> bool: ...

    async def count(self, table: str, where: str = "",
                    params: tuple = ()) -> int: ...

    async def paginate(
        self, table: str, page: int = 1, size: int = 4,
        order_by: str = "created_at DESC",
        where: str = "", params: tuple = (),
    ) -> dict[str, Any]: ...
