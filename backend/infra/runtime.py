"""Holds a reference to the main asyncio event loop.

Set once in `bootstrap/app.py` lifespan. Used by tools that run on a
worker thread (e.g. inside `asyncio.to_thread(crew.kickoff)`) but need to
schedule coroutines on the main loop where aiosqlite / WebSocket state
is bound.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once at app startup with the FastAPI lifespan loop."""
    global _main_loop
    _main_loop = loop


def get_main_loop() -> asyncio.AbstractEventLoop | None:
    return _main_loop


def run_on_main_loop(coro: Awaitable[Any]) -> Any:
    """Schedule a coroutine on the main loop from a worker thread; block
    until it completes; return its result (or raise its exception).

    Raises RuntimeError if `set_main_loop` was never called.
    """
    loop = _main_loop
    if loop is None:
        raise RuntimeError(
            "infra.runtime: main loop not registered. "
            "bootstrap.app.lifespan should call set_main_loop() at startup."
        )
    if loop.is_closed():
        raise RuntimeError("infra.runtime: main loop is closed")
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()
