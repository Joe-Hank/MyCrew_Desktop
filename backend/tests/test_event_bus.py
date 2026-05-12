"""Tests for InMemoryEventBus — subscribe, publish, error handling."""
import pytest

from domain.events import DomainEvent, ProjectStarted, TaskCompleted
from infra.event_bus.in_memory_bus import InMemoryEventBus


class TestInMemoryEventBus:
    async def test_subscribe_and_publish(self):
        bus = InMemoryEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(ProjectStarted, handler)
        await bus.publish(ProjectStarted(project_id="p1"))

        assert len(received) == 1
        assert received[0].project_id == "p1"

    async def test_subscribe_all(self):
        bus = InMemoryEventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe_all(handler)
        await bus.publish(ProjectStarted(project_id="p1"))
        await bus.publish(TaskCompleted(project_id="p1", task_id="t1"))

        assert len(received) == 2

    async def test_type_specific_filtering(self):
        bus = InMemoryEventBus()
        project_events = []
        task_events = []

        async def proj_handler(e):
            project_events.append(e)

        async def task_handler(e):
            task_events.append(e)

        bus.subscribe(ProjectStarted, proj_handler)
        bus.subscribe(TaskCompleted, task_handler)

        await bus.publish(ProjectStarted(project_id="p1"))
        await bus.publish(TaskCompleted(project_id="p1", task_id="t1"))

        assert len(project_events) == 1
        assert len(task_events) == 1

    async def test_handler_error_doesnt_stop_others(self):
        bus = InMemoryEventBus()
        received = []

        async def bad_handler(event):
            raise RuntimeError("boom")

        async def good_handler(event):
            received.append(event)

        bus.subscribe(ProjectStarted, bad_handler)
        bus.subscribe(ProjectStarted, good_handler)

        await bus.publish(ProjectStarted(project_id="p1"))
        assert len(received) == 1

    async def test_publish_all(self):
        bus = InMemoryEventBus()
        received = []

        async def handler(e):
            received.append(e)

        bus.subscribe_all(handler)
        events = [
            ProjectStarted(project_id="p1"),
            TaskCompleted(project_id="p1", task_id="t1"),
        ]
        await bus.publish_all(events)
        assert len(received) == 2

    async def test_no_subscribers(self):
        bus = InMemoryEventBus()
        await bus.publish(ProjectStarted(project_id="p1"))
