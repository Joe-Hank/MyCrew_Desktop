"""In-memory event bus — dispatches domain events to registered handlers."""
from __future__ import annotations

import asyncio
from collections import defaultdict

import structlog

from domain.events import DomainEvent
from ports.event_bus_port import EventHandler

log = structlog.get_logger()


class InMemoryEventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []

    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        self._global_handlers.append(handler)

    async def publish(self, event: DomainEvent) -> None:
        handlers = list(self._handlers.get(type(event), []))
        handlers.extend(self._global_handlers)

        for handler in handlers:
            try:
                await handler(event)
            except Exception as exc:
                log.error("event_bus.handler_error",
                          event=type(event).__name__, error=str(exc))

    async def publish_all(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)


event_bus = InMemoryEventBus()
