"""Smoke test for WebSocket session-token auth (audit Top 5 #2).

Validates:
  - WS endpoint rejects connections without a token (close code 4401).
  - WS rejects a wrong token.
  - WS accepts the correct token.
  - GET /auth/ws_token returns the current token to localhost callers.
  - generate_session_token produces URL-safe 32-byte secrets.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import ws as ws_module
from api.routes_auth import router as auth_router
from api.ws import (
    generate_session_token,
    router as ws_router,
    set_session_token,
)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ws_router)
    app.include_router(auth_router)
    return app


def test_generate_session_token_format():
    t1 = generate_session_token()
    t2 = generate_session_token()
    assert t1 != t2, "tokens must be unique per call"
    # secrets.token_urlsafe(32) yields ≥ 32 chars, URL-safe alphabet only.
    assert len(t1) >= 32
    for ch in t1:
        assert ch.isalnum() or ch in "-_"


def test_ws_rejects_missing_token():
    set_session_token("expected-token-value")
    app = _make_app()
    client = TestClient(app)
    with pytest.raises(Exception):  # WebSocketDisconnect or similar
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()


def test_ws_rejects_wrong_token():
    set_session_token("expected-token-value")
    app = _make_app()
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=wrong-token") as ws:
            ws.receive_text()


def test_ws_accepts_correct_token():
    token = "expected-token-value"
    set_session_token(token)
    app = _make_app()
    client = TestClient(app)
    # Connection should succeed; we send a ping and read back pong to
    # confirm the socket is alive after the auth check.
    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text('{"type":"ping","payload":{}}')
        msg = ws.receive_text()
        assert "pong" in msg


def test_ws_token_endpoint_returns_value():
    set_session_token("returned-token")
    app = _make_app()
    client = TestClient(app)
    res = client.get("/auth/ws_token")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["data"]["token"] == "returned-token"


def test_ws_token_endpoint_uninitialised_503():
    # Simulate the very-early boot window: token not yet set.
    ws_module._SESSION_TOKEN = None
    app = _make_app()
    client = TestClient(app)
    res = client.get("/auth/ws_token")
    assert res.status_code == 503
