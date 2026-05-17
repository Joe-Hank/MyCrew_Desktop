"""桩：WsInteraction 超时回退 / resolve 路径契约。

Why
---
`infra/interaction/ws_interaction.py` implements the InteractionPort
by broadcasting a `prompt.request` over WS and awaiting a matching
`prompt.response`. Two things matter and are currently untested:

  1. **Timeout fallback.** When no `prompt.response` arrives within
     DEFAULT_TIMEOUT (300s), `_send_and_wait` swallows asyncio.TimeoutError
     and returns `{}`. That `{}` then bubbles back through `prompt_choice`
     / `prompt_text` / `prompt_confirm`, each of which has its own
     fallback:
       - prompt_choice → first option's value (or empty string)
       - prompt_text   → empty string
       - prompt_confirm → False  (the value "{}".get('value') is None)
     If any of these regress, a stuck UI silently feeds wrong defaults
     into the workflow.

  2. **resolve() races with timeout.** If `resolve(request_id, response)`
     is called for an already-completed future, it must be a no-op
     (guard: `if fut and not fut.done()`). Without this guard a late
     response would crash the WS handler.

Suggested approach
------------------
Drop DEFAULT_TIMEOUT to ~0.05s via monkey-patch and use a fake
broadcast_fn that records calls. The internal `_pending` dict is the
right injection point for "force a timeout" tests.

Stubs only — flip xfail when implemented.
"""
from __future__ import annotations

import pytest

# import asyncio
# from infra.interaction.ws_interaction import WsInteraction
# from ports.interaction_port import PromptCtx, Choice

TODO = pytest.mark.xfail(reason="todo: ws_interaction stub", strict=False)


class TestPromptChoiceTimeout:
    @TODO
    async def test_timeout_returns_first_option_value(self):
        """No resolve() call within timeout → returns options[0].value."""
        raise NotImplementedError

    @TODO
    async def test_timeout_with_no_options_returns_empty_string(self):
        raise NotImplementedError

    @TODO
    async def test_pending_entry_cleaned_up_after_timeout(self):
        """The `_pending` dict should not leak request_id on timeout —
        the `finally:` block in _send_and_wait pops it."""
        raise NotImplementedError


class TestPromptTextTimeout:
    @TODO
    async def test_timeout_returns_empty_string(self):
        raise NotImplementedError


class TestPromptConfirmTimeout:
    @TODO
    async def test_timeout_resolves_to_false(self):
        """Timeout → response is {} → {}.get('value') is None → False.
        Pin this contract because turning a timeout into a *confirm* would
        be a destructive default."""
        raise NotImplementedError

    @TODO
    async def test_true_value_normalised_from_string_yes(self):
        """resolve() with response={'value': 'yes'} should still produce
        True — the (True, 'true', 'yes', '1') tuple in prompt_confirm
        is a normalisation contract worth pinning."""
        raise NotImplementedError


class TestResolveRaces:
    @TODO
    async def test_resolve_unknown_request_id_is_noop(self):
        """resolve('never-sent', {...}) must not raise."""
        raise NotImplementedError

    @TODO
    async def test_resolve_after_timeout_is_noop(self):
        """Late response (after the future has been cancelled by timeout)
        must not crash."""
        raise NotImplementedError

    @TODO
    async def test_resolve_delivers_value_before_timeout(self):
        """Happy path: resolve() within the window → await returns the
        supplied response dict."""
        raise NotImplementedError


class TestBroadcastWiring:
    @TODO
    async def test_send_without_broadcast_raises_runtime_error(self):
        """If `set_broadcast(fn)` was never called, _send_and_wait raises
        RuntimeError('WsInteraction not connected to broadcast'). This
        is the only synchronous failure mode and is worth pinning."""
        raise NotImplementedError

    @TODO
    async def test_broadcast_payload_includes_request_id(self):
        """The outgoing payload's request_id must match the one the
        future is keyed on, otherwise resolve() can never find it."""
        raise NotImplementedError
