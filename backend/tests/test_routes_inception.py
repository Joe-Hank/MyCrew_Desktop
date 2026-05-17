"""桩：FastAPI routes_inception 路由层契约测试。

Why
---
Phase 12 review flagged that we have zero API-layer tests for the
inception flow — every existing inception test pokes the service
directly via patched `inception_svc.crud` / `llm_gateway`. That leaves
the request-shape and error-translation logic in `api/routes_inception.py`
unguarded:

  - POST /inceptions/sessions               body → SessionCreate
  - POST /inceptions/sessions/{id}/choices  body → SessionChoice
  - PATCH /inceptions/sessions/{id}         rename
  - POST /inceptions/sessions/{id}/finalize blueprint extraction
  - DELETE /inceptions/sessions/{id}

The route layer is thin but does carry the (KeyError → 404 /
ValueError → 400 invalid_choice) translation that the frontend depends
on. When that mapping drifts, the inception drawer's error UX
silently degrades.

Suggested approach
------------------
Use FastAPI's TestClient with `inception_svc` replaced by a stub
(MagicMock) — we don't need to exercise the real service here, only
the request/response wiring.

Stubs only; flip xfail when implemented.
"""
from __future__ import annotations

import pytest

# from fastapi.testclient import TestClient
# from unittest.mock import AsyncMock, patch
# from api.routes_inception import router

TODO = pytest.mark.xfail(reason="todo: route-layer stub", strict=False)


class TestCreateSessionRoute:
    @TODO
    def test_post_minimal_body(self):
        """POST /inceptions/sessions with only llm_id should succeed and
        return {ok: true, data: {...}}."""
        raise NotImplementedError

    @TODO
    def test_post_with_template_id(self):
        """Body carries template_id — must reach inception_svc.create_session
        as keyword arg. This is the pre-baked-template path."""
        raise NotImplementedError

    @TODO
    def test_post_with_iterate_mode_and_parent(self):
        """mode='iterate' + parent_project_id forwarded as kwargs."""
        raise NotImplementedError

    @TODO
    def test_post_rejects_invalid_body_with_422(self):
        """Pydantic validation: missing llm_id → 422."""
        raise NotImplementedError


class TestSubmitChoiceRoute:
    @TODO
    def test_choice_with_template_id_returns_ok(self):
        raise NotImplementedError

    @TODO
    def test_choice_unknown_session_returns_404(self):
        """inception_svc.apply_choice raises KeyError → HTTPException(404)."""
        raise NotImplementedError

    @TODO
    def test_choice_invalid_template_returns_invalid_choice_envelope(self):
        """ValueError from apply_choice is translated to
        {ok: false, error: {code: 'invalid_choice', ...}} — frontend
        looks at envelope.error.code to render inline."""
        raise NotImplementedError


class TestRenameSessionRoute:
    @TODO
    def test_patch_with_title_succeeds(self):
        raise NotImplementedError

    @TODO
    def test_patch_with_empty_title_clears(self):
        """Empty string is the documented "revert to project_name" signal."""
        raise NotImplementedError

    @TODO
    def test_patch_unknown_session_returns_404(self):
        raise NotImplementedError


class TestListSessionsRoute:
    @TODO
    def test_list_default_pagination(self):
        """GET /inceptions/sessions default limit=10 offset=0."""
        raise NotImplementedError

    @TODO
    def test_list_with_search_query(self):
        """`?q=foo` reaches inception_svc.list_sessions(search='foo')."""
        raise NotImplementedError

    @TODO
    def test_list_limit_bounds_validated(self):
        """limit > 200 → 422 (FastAPI Query validator)."""
        raise NotImplementedError


class TestDeleteSessionRoute:
    @TODO
    def test_delete_success(self):
        raise NotImplementedError

    @TODO
    def test_delete_unknown_session_returns_404(self):
        raise NotImplementedError
