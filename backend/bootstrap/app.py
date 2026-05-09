from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bootstrap.paths import ensure_dirs

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("startup.begin")
    ensure_dirs()
    # STEP 1: load app config (Phase 2)
    # STEP 2: init SQLite + run migrations
    from infra.repo.sqlite_repo import init_db

    await init_db()
    log.info("startup.db_ready")
    # STEP 3: load static config (Phase 2)
    # STEP 4: scan user tools (Phase 3)
    # STEP 5: check last_state.json (Phase 6)
    # STEP 6: auto-start MCP pool (Phase 3)
    log.info("startup.complete")
    yield
    log.info("shutdown.begin")
    # shutdown sequence (Phase 6)
    log.info("shutdown.complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="MyCrew Backend",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:1420", "http://127.0.0.1:1420", "tauri://localhost"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from api.routes_health import router as health_router
    from api.ws import router as ws_router

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")

    return app
