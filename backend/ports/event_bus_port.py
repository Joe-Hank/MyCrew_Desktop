from __future__ import annotations

from typing import Any, Callable, Coroutine, Protocol

from domain.events import DomainEvent

EventHandler = Callable[[DomainEvent], Coroutine[Any, Any, None]]


class EventBusPort(Protocol):
    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None: ...
    async def publish(self, event: DomainEvent) -> None: ...
