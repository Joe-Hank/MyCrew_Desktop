"""Smoke test for _output_capture TTL eviction (audit Phase 2).

The capture buckets used to grow without bound — a crashed task or a
PM round that died before clear_planner_session would leave its payload
in memory forever. The TTL ensures stale entries are dropped on the
next set/pop call.
"""
from __future__ import annotations

import time

import pytest

import src.tools.builtin.local._output_capture as capture


@pytest.fixture(autouse=True)
def _isolate():
    # Each test starts from empty buckets so cross-test pollution can't
    # mask a regression in a peer test.
    capture._outputs.clear()
    capture._planner_outputs.clear()
    yield
    capture._outputs.clear()
    capture._planner_outputs.clear()


def test_task_output_evicted_after_ttl(monkeypatch):
    monkeypatch.setattr(capture, "_TASK_OUTPUT_TTL_S", 0.01)
    capture.set_output("t1", {"file_path": "x.png"})
    assert capture.has_output("t1")
    time.sleep(0.02)
    # A later operation triggers _evict_expired; the entry should be gone.
    assert capture.pop_output("t1") is None
    assert not capture.has_output("t1")


def test_planner_output_evicted_after_ttl(monkeypatch):
    monkeypatch.setattr(capture, "_PLANNER_OUTPUT_TTL_S", 0.01)
    capture.set_planner_output("sess1", "concept", {"title": "T"})
    time.sleep(0.02)
    assert capture.pop_planner_output("sess1", "concept") is None


def test_task_output_within_ttl_survives(monkeypatch):
    monkeypatch.setattr(capture, "_TASK_OUTPUT_TTL_S", 5.0)
    capture.set_output("t1", {"keep": True})
    # No sleep — pop should still return the value.
    assert capture.pop_output("t1") == {"keep": True}


def test_clear_planner_session_drops_only_matching():
    capture.set_planner_output("A", "concept", {"x": 1})
    capture.set_planner_output("A", "review", {"x": 2})
    capture.set_planner_output("B", "concept", {"x": 3})
    capture.clear_planner_session("A")
    assert capture.pop_planner_output("A", "concept") is None
    assert capture.pop_planner_output("A", "review") is None
    assert capture.pop_planner_output("B", "concept") == {"x": 3}
