import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from bootstrap.paths import ensure_dirs

log = structlog.get_logger()


# Methods we treat as "mutations" — recorded in the audit event log so
# the Brain (and the LogDrawer) can later replay who changed what.
_AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths to NEVER audit — high-volume streaming endpoints whose semantics
# are already covered by the inception.* / agent.output events.
_AUDIT_SKIP_PREFIXES = (
    "/api/v1/ws",
    "/api/v1/inceptions/sessions/",   # message streams handle their own
    "/api/v1/events",                  # don't audit reads of audit log
)


async def _audit_middleware(request: Request, call_next):
    """Record every mutation API call into the events table.

    Captures: method, path, status_code, latency_ms, query params (no body
    to avoid blowing up the row size — sensitive bodies like LLM keys live
    in PUT /llm/* requests and we don't want them in the audit table)."""
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        # Let the framework's error handler send the response; we still
        # log the attempt so the audit trail isn't dark on crashes.
        latency_ms = int((time.monotonic() - started) * 1000)
        await _record_mutation(request, status=500, latency_ms=latency_ms)
        raise

    if (request.method in _AUDIT_METHODS
            and not any(request.url.path.startswith(p)
                        for p in _AUDIT_SKIP_PREFIXES)):
        latency_ms = int((time.monotonic() - started) * 1000)
        await _record_mutation(
            request, status=response.status_code, latency_ms=latency_ms,
        )
    return response


async def _record_mutation(request: Request, status: int, latency_ms: int) -> None:
    """Fire-and-forget audit write; never raises."""
    try:
        from services.events_svc import record_event
        await record_event(
            "api.mutation",
            {
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query) if request.url.query else "",
                "status": status,
                "latency_ms": latency_ms,
            },
            actor="user",  # all UI-originating mutations are user-driven
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("audit.mutation_record_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("startup.begin")
    ensure_dirs()

    # STEP 0: register main loop so worker-thread tools can hop back to it
    import asyncio
    from infra.runtime import set_main_loop
    set_main_loop(asyncio.get_running_loop())

    # STEP 1: load app config
    from infra.config_loader import load_app_config
    app_config = load_app_config()
    log.info("startup.config_loaded", theme=app_config.get("theme"))

    # STEP 2: init SQLite + run migrations
    from infra.repo.sqlite_repo import init_db, close_db
    await init_db()
    log.info("startup.db_ready")

    # STEP 2.5: seed builtin tools + Plan Maker agent (idempotent)
    from bootstrap.seed_builtin_tools import ensure_builtin_tools
    from bootstrap.seed_plan_maker import ensure_plan_maker_agent
    tool_ids = await ensure_builtin_tools()
    await ensure_plan_maker_agent(tool_ids)
    log.info("startup.seeded")

    # WS connection manager — imported up front because steps 3/4/5 all use it
    from api.ws import manager

    # STEP 3: start MCP connection pool
    from services.mcp_svc import mcp_svc
    from infra.mcp.pool import mcp_pool

    mcp_pool.set_broadcast(manager.broadcast)
    await mcp_svc.start_pool()
    log.info("startup.mcp_pool_ready")

    # STEP 4: wire event bus → WS broadcast + interaction port
    from infra.event_bus.in_memory_bus import event_bus
    from infra.interaction.ws_interaction import ws_interaction
    from domain.events import DomainEvent

    async def _forward_event_to_ws(event: DomainEvent) -> None:
        event_name = type(event).__name__
        # Convert CamelCase to dot.notation for WS
        import re
        ws_type = re.sub(r"(?<!^)(?=[A-Z])", ".", event_name).lower()
        payload = {k: v for k, v in event.__dict__.items() if k != "ts"}
        await manager.broadcast(ws_type, payload)

    event_bus.subscribe_all(_forward_event_to_ws)
    ws_interaction.set_broadcast(manager.broadcast)
    log.info("startup.event_bus_ready")

    # STEP 5: check last_state.json for recovery
    from infra.config_loader import load_last_state, clear_last_state

    last_state = load_last_state()
    if last_state and last_state.get("paused_projects"):
        projects = last_state["paused_projects"]
        log.info("startup.recovery_available", projects=len(projects))
        await manager.broadcast("lifecycle.recovery_prompt", {
            "projects": projects,
        })
    clear_last_state()

    # STEP 6: start stall-detection watchdog + reconcile orphan-running
    # projects from previous run (state=running but no live harness now).
    # Without this, a project that crashed mid-run during a previous
    # session shows blue "in progress" forever.
    from services.watchdog_svc import run_watchdog, reconcile_all_orphans_on_startup
    await reconcile_all_orphans_on_startup()
    watchdog_task = asyncio.create_task(run_watchdog())
    log.info("startup.watchdog_started")

    # STEP 7: event-log janitor (6h cadence; drops rows past retention)
    from services.events_svc import run_event_janitor
    events_janitor_task = asyncio.create_task(run_event_janitor())
    log.info("startup.events_janitor_started")

    log.info("startup.complete")
    yield

    # Shutdown sequence
    log.info("shutdown.begin")

    # Stop watchdog + janitor before MCP teardown
    for t in (watchdog_task, events_janitor_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    # Gracefully stop MCP pool (signals → wait → force kill)
    await mcp_svc.shutdown_all()
    log.info("shutdown.mcp_pool_stopped")

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

    # Mutation audit — every POST/PUT/PATCH/DELETE writes one row into
    # `events` so the Brain (and the LogDrawer) sees what UI did. Reads
    # are skipped to keep table small.
    app.middleware("http")(_audit_middleware)

    from api.routes_health import router as health_router
    from api.ws import router as ws_router
    from api.routes_llm import router as llm_router
    from api.routes_mcp import router as mcp_router
    from api.routes_config import router as config_router
    from api.routes_workflow import router as workflow_router
    from api.routes_project import router as project_router
    from api.routes_inception import router as inception_router
    from api.routes_files import router as files_router
    from api.routes_agent import router as agent_router
    from api.routes_crew import router as crew_router
    from api.routes_tool import router as tool_router
    from api.routes_lifecycle import router as lifecycle_router
    from api.routes_template import router as template_router
    from api.routes_events import router as events_router
    from api.routes_storage import router as storage_router

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(ws_router, prefix="/api/v1")
    app.include_router(llm_router, prefix="/api/v1")
    app.include_router(mcp_router, prefix="/api/v1")
    app.include_router(config_router, prefix="/api/v1")
    app.include_router(workflow_router, prefix="/api/v1")
    app.include_router(project_router, prefix="/api/v1")
    app.include_router(inception_router, prefix="/api/v1")
    app.include_router(files_router, prefix="/api/v1")
    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(crew_router, prefix="/api/v1")
    app.include_router(tool_router, prefix="/api/v1")
    app.include_router(lifecycle_router, prefix="/api/v1")
    app.include_router(template_router, prefix="/api/v1")
    app.include_router(events_router, prefix="/api/v1")
    app.include_router(storage_router, prefix="/api/v1")

    return app
