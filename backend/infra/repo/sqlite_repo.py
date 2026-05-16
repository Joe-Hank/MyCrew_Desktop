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
        # busy_timeout (audit 2026-05-16 followup): when another process
        # — orphaned test runs, dev scripts that hung — holds the write
        # lock briefly, default behaviour is to raise "database is locked"
        # immediately. 5s timeout lets SQLite retry transparently and
        # absorbs cross-process contention without surfacing it to the
        # event log path or the seed pipeline.
        await _db.execute("PRAGMA busy_timeout=5000")
        await _db.execute("PRAGMA synchronous=NORMAL")
        # Bound the WAL size on connect — abandoned test runs left a
        # 4MB WAL (incident 2026-05-16 14:20) that thrashed write locks
        # during seed UPDATEs. TRUNCATE forces all pending WAL pages
        # into the main DB and resets the WAL file to zero.
        try:
            await _db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await _db.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("db.wal_checkpoint_failed", error=str(exc))
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
