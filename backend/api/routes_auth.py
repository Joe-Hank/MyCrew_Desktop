"""Localhost-only auth endpoints — returns the WS session token.

Added 2026-05-16 (audit Top 5 #2). The frontend calls
`GET /api/v1/auth/ws_token` once on startup, caches the token, and
appends it to every WebSocket URL (`ws://localhost:<port>/api/v1/ws?token=…`).
Without this token the WS handshake is rejected with code 4401.

Why a separate endpoint instead of bundling the token into the home /
config response: the WS subsystem is a security boundary on its own,
and pinning the token to a dedicated route keeps the contract obvious
and easy to lock down (e.g. add rate-limiting later without touching
unrelated routes).
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request

from api.ws import get_session_token

log = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])


# Pin to localhost — the WS itself is local-only, so the token endpoint
# should be too. A foreign tab could still hit this URL via fetch from
# a different origin, but CORS limits which origins receive the body;
# combined with the Host check it's belt + suspenders.
# "testclient" is FastAPI's TestClient peer host; allowing it keeps the
# unit-test path identical to production behaviour.
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "testclient", None}


@router.get("/ws_token")
async def get_ws_token(request: Request):
    client_host = request.client.host if request.client else None
    if client_host not in _LOCAL_HOSTS:
        log.warning("auth.ws_token_remote_rejected", host=client_host)
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        token = get_session_token()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="session not initialised")
    return {"ok": True, "data": {"token": token}}
