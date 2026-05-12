"""Tests for TaskRunner — input preparation, output processing, retry logic, execution order."""
import json
import pytest

from domain.harness.task_runner import TaskRunner, TaskInput, TaskOutput


def _tasks(specs: list[dict]) -> list[dict]:
    result = []
    for s in specs:
        result.append({
            "id": s["id"],
            "title": s.get("title", f"Task {s['id']}"),
            "detail": s.get("detail", ""),
            "status": s.get("status", "pending"),
            "deps": s.get("deps", []),
            "output_schema": s.get("output_schema", {}),
            "agent_id": s.get("agent_id", "agent_1"),
            "kind": s.get("kind", "regular"),
            "max_retry": s.get("max_retry", 3),
        })
    return result


class TestPrepareInput:
    def test_basic_input(self):
        runner = TaskRunner(_tasks([{"id": "t1"}]))
        inp = runner.prepare_input("t1", {})

        assert isinstance(inp, TaskInput)
        assert inp.task_id == "t1"
        assert inp.agent_id == "agent_1"
        assert inp.upstream_outputs == {}

    def test_collects_upstream_outputs(self):
        runner = TaskRunner(_tasks([
            {"id": "t1"},
            {"id": "t2", "deps": ["t1"]},
        ]))
        completed = {"t1": {"result": "hello"}}
        inp = runner.prepare_input("t2", completed)

        assert inp.upstream_outputs == {"t1": {"result": "hello"}}

    def test_missing_upstream_ignored(self):
        runner = TaskRunner(_tasks([
            {"id": "t1"},
            {"id": "t2", "deps": ["t1"]},
        ]))
        inp = runner.prepare_input("t2", {})
        assert inp.upstream_outputs == {}

    def test_output_schema_string_parsed(self):
        runner = TaskRunner(_tasks([{
            "id": "t1",
            "output_schema": '{"type": "object"}',
        }]))
        inp = runner.prepare_input("t1", {})
        assert inp.output_schema == {"type": "object"}

    def test_output_schema_invalid_string_becomes_empty(self):
        runner = TaskRunner(_tasks([{
            "id": "t1",
            "output_schema": "not valid json",
        }]))
        inp = runner.prepare_input("t1", {})
        assert inp.output_schema == {}


class TestProcessOutput:
    def test_free_text_output(self):
        runner = TaskRunner(_tasks([{"id": "t1"}]))
        out = runner.process_output("t1", "hello world", None, None)

        assert out.is_valid
        assert out.structured == {"_raw": "hello world"}

    def test_valid_structured_output(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        runner = TaskRunner(_tasks([{"id": "t1", "output_schema": schema}]))
        out = runner.process_output("t1", "raw", {"name": "test"}, [])

        assert out.is_valid
        assert out.structured == {"name": "test"}

    def test_validation_errors_make_output_invalid(self):
        schema = {"type": "object", "required": ["name"]}
        runner = TaskRunner(_tasks([{"id": "t1", "output_schema": schema}]))
        out = runner.process_output("t1", "raw", None, ["missing 'name'"])

        assert not out.is_valid
        assert out.validation_errors == ["missing 'name'"]


class TestShouldRetry:
    def test_within_limit(self):
        runner = TaskRunner(_tasks([{"id": "t1", "max_retry": 3}]))
        assert runner.should_retry("t1", 0) is True
        assert runner.should_retry("t1", 1) is True
        assert runner.should_retry("t1", 2) is True

    def test_at_limit(self):
        runner = TaskRunner(_tasks([{"id": "t1", "max_retry": 3}]))
        assert runner.should_retry("t1", 3) is False

    def test_default_max_retry(self):
        runner = TaskRunner(_tasks([{"id": "t1"}]))
        assert runner.should_retry("t1", 2) is True
        assert runner.should_retry("t1", 3) is False


class TestExecutionOrder:
    def test_linear_chain(self):
        runner = TaskRunner(_tasks([
            {"id": "t1"},
            {"id": "t2", "deps": ["t1"]},
            {"id": "t3", "deps": ["t2"]},
        ]))
        waves = runner.get_execution_order()
        assert waves == [["t1"], ["t2"], ["t3"]]

    def test_parallel_fork_join(self):
        runner = TaskRunner(_tasks([
            {"id": "t1"},
            {"id": "t2", "deps": ["t1"]},
            {"id": "t3", "deps": ["t1"]},
            {"id": "t4", "deps": ["t2", "t3"]},
        ]))
        waves = runner.get_execution_order()
        assert len(waves) == 3
        assert waves[0] == ["t1"]
        assert set(waves[1]) == {"t2", "t3"}
        assert waves[2] == ["t4"]

    def test_independent_tasks_single_wave(self):
        runner = TaskRunner(_tasks([
            {"id": "t1"},
            {"id": "t2"},
            {"id": "t3"},
        ]))
        waves = runner.get_execution_order()
        assert len(waves) == 1
        assert set(waves[0]) == {"t1", "t2", "t3"}

    def test_cyclic_deps_breaks(self):
        runner = TaskRunner(_tasks([
            {"id": "t1", "deps": ["t2"]},
            {"id": "t2", "deps": ["t1"]},
        ]))
        waves = runner.get_execution_order()
        assert waves == []

    def test_empty_tasks(self):
        runner = TaskRunner([])
        assert runner.get_execution_order() == []
