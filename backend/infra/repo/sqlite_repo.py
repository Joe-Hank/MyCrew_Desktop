from __future__ import annotations

import asyncio
import aiosqlite
import structlog

from bootstrap.paths import DB_PATH

log = structlog.get_logger()

_db: aiosqlite.Connection | None = None


def _run_migrations() -> None:
    from alembic.config import Config
    from alembic import command
    from bootstrap.paths import PROJECT_ROOT

    alembic_cfg = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "backend" / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH.as_posix()}")
    command.upgrade(alembic_cfg, "head")


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def init_db() -> None:
    await asyncio.to_thread(_run_migrations)
    log.info("db.migrations_applied")
    await get_db()
    log.info("db.connected", path=str(DB_PATH))


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None
