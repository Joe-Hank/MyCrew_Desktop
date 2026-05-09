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

    # STEP 1: load app config
    from infra.config_loader import load_app_config
    app_config = load_app_config()
    log.info("startup.config_loaded", theme=app_config.get("theme"))

    # STEP 2: init SQLite + run migrations
    from infra.repo.sqlite_repo import init_db, close_db
    await init_db()
    log.info("startup.db_ready")

    # STEP 3: load static config into services (Phase 3+)

    # STEP 4: scan user tools (Phase 7)

    # STEP 5: check last_state.json for recovery
    from infra.config_loader import load_last_state, clear_last_state
    from api.ws import manager

    last_state = load_last_state()
    if last_state and last_state.get("paused_projects"):
        projects = last_state["paused_projects"]
        log.info("startup.recovery_available", projects=len(projects))
        await manager.broadcast("lifecycle.recovery_prompt", {
            "projects": projects,
        })
    clear_last_state()

    # STEP 6: auto-start MCP pool (Phase 3)

    log.info("startup.complete")
    yield

    # Shutdown sequence
    log.info("shutdown.begin")

    # Save last state for recovery
    from infra.config_loader import save_last_state
    save_last_state({"paused_projects": [], "ts": __import__("datetime").datetime.now().isoformat()})

    await close_db()
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
    from api.routes_llm import router as llm_router
    from api.routes_mcp import router as mcp_router
    from api.routes_config import router as config_router

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")
    app.include_router(llm_router, prefix="/api/v1")
    app.include_router(mcp_router, prefix="/api/v1")
    app.include_router(config_router, prefix="/api/v1")

    return app
