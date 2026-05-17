import os
import sys
import socket

import uvicorn
import structlog

from bootstrap.paths import DEFAULT_PORT, PORT_RANGE
from infra.log_pipeline import tap_processor

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        # 2026-05-17 T1: tap the structured log into 3 sinks (rotating
        # file at data/logs/mycrew.log, in-memory ring buffer for the
        # /logs replay endpoint, and the WS log.line channel for live
        # LogDrawer streaming). Placed AFTER add_log_level + TimeStamper
        # so the snapshot already has ts + level, and BEFORE the final
        # renderer so stdout still gets a clean console/JSON line.
        tap_processor,
        structlog.dev.ConsoleRenderer() if os.getenv("MYCREW_DEV") == "1"
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.get_config()["wrapper_class"].level
        if hasattr(structlog.get_config().get("wrapper_class", object), "level")
        else 0
    ),
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()


def find_free_port() -> int:
    for port in PORT_RANGE:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    log.error("no_free_port", range=f"{PORT_RANGE.start}-{PORT_RANGE.stop}")
    sys.exit(1)


def main() -> None:
    port = DEFAULT_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            port = find_free_port()

    log.info("backend.starting", port=port)
    # Print port on stdout for Tauri sidecar handshake
    print(f"MYCREW_PORT={port}", flush=True)

    uvicorn.run(
        "bootstrap.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port,
        log_level=os.getenv("MYCREW_LOG_LEVEL", "info").lower(),
        reload=os.getenv("MYCREW_DEV") == "1",
        reload_dirs=["api", "services", "domain", "ports", "infra", "bootstrap"]
        if os.getenv("MYCREW_DEV") == "1"
        else None,
    )


if __name__ == "__main__":
    main()
