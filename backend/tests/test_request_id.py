"""Smoke test for the request_id middleware (audit Phase 2 dim 7).

Verifies:
  - Every response has an X-Request-ID header.
  - Client-supplied X-Request-ID is honoured (frontend can pass its own).
  - Auto-generated ids are short hex strings.
  - structlog contextvar carries the rid while the request is in flight,
    and is cleared afterwards.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from bootstrap.app import _request_id_middleware


def _make_app():
    app = FastAPI()
    app.middleware("http")(_request_id_middleware)

    @app.get("/echo")
    async def echo(request: Request):
        # While handling, the structlog contextvar should be bound.
        ctx = structlog.contextvars.get_contextvars()
        return {
            "rid_state": request.state.request_id,
            "rid_ctxvar": ctx.get("request_id", ""),
        }
    return app


def test_response_carries_x_request_id():
    app = _make_app()
    client = TestClient(app)
    res = client.get("/echo")
    assert res.status_code == 200
    rid = res.headers.get("X-Request-ID", "")
    assert rid
    assert res.json()["rid_state"] == rid
    assert res.json()["rid_ctxvar"] == rid


def test_client_supplied_request_id_is_honoured():
    app = _make_app()
    client = TestClient(app)
    res = client.get("/echo", headers={"X-Request-ID": "abc123-from-frontend"})
    assert res.headers["X-Request-ID"] == "abc123-from-frontend"
    assert res.json()["rid_state"] == "abc123-from-frontend"


def test_request_id_is_unbound_after_request():
    app = _make_app()
    client = TestClient(app)
    client.get("/echo")
    # After the request finishes, the contextvar should be cleared so
    # a later log emit (from a long-lived worker, e.g.) doesn't inherit
    # the previous request's id.
    ctx = structlog.contextvars.get_contextvars()
    assert "request_id" not in ctx


def test_generated_ids_are_short_hex():
    app = _make_app()
    client = TestClient(app)
    seen = set()
    for _ in range(5):
        res = client.get("/echo")
        rid = res.headers["X-Request-ID"]
        seen.add(rid)
        assert len(rid) == 12
        assert all(c in "0123456789abcdef" for c in rid)
    assert len(seen) == 5  # each request gets a unique id
