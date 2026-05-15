"""Smoke test for emit_output file-path validation (PM v4 Q4).

The 「霓虹攀升」 incident exposed that the previous _PATH_FIELD_NAMES list
only matched the singular forms (file_path / image_path / ...), so an
agent could submit a `file_paths: [...]` array of nine sprite paths and
have emit_output silently accept it — 0 paths verified, on-disk empty.

This test pins down the fix:
  - plural keys (file_paths / output_paths) get gathered
  - their list-of-strings values get walked
  - the existence check now sees every claimed path
"""
from __future__ import annotations

from pathlib import Path

from src.tools.builtin.local.emit_output import (
    _PATH_FIELD_NAMES,
    _gather_paths,
    make_emit_output_tool,
)
from src.tools.builtin.local._output_capture import pop_output


def test_plural_keys_registered():
    for k in ("file_paths", "output_paths", "filepaths", "paths"):
        assert k in _PATH_FIELD_NAMES, f"{k} must be in _PATH_FIELD_NAMES"


def test_gather_singular_file_path():
    out: list[str] = []
    _gather_paths({"file_path": "a/b.png"}, out)
    assert out == ["a/b.png"]


def test_gather_plural_file_paths_list():
    out: list[str] = []
    _gather_paths(
        {"file_paths": ["a/b.png", "a/c.png", "  trim.png  "]},
        out,
    )
    assert out == ["a/b.png", "a/c.png", "trim.png"]


def test_gather_plural_output_paths_nested():
    out: list[str] = []
    _gather_paths(
        {"result": {"output_paths": ["x.cs", "y.cs"]}},
        out,
    )
    assert out == ["x.cs", "y.cs"]


def test_gather_skips_non_string_list_items():
    out: list[str] = []
    _gather_paths({"file_paths": [None, 1, "", "ok.png"]}, out)
    assert out == ["ok.png"]


def test_emit_output_rejects_missing_plural_paths(tmp_path: Path):
    real_file = tmp_path / "real.png"
    real_file.write_bytes(b"\x89PNG\r\n\x1a\n")

    tool = make_emit_output_tool(
        task_id="task_test_plural",
        output_schema={},
        project_root=str(tmp_path),
    )
    result = tool._run(
        {
            "file_paths": [
                "real.png",       # exists
                "ghost1.png",     # does NOT exist
                "ghost2.png",
            ]
        }
    )
    assert "[ValidationError]" in result
    assert "ghost1.png" in result
    assert "ghost2.png" in result
    # Nothing should have been captured for this task
    assert pop_output("task_test_plural") is None


def test_emit_output_accepts_plural_paths_when_all_exist(tmp_path: Path):
    f1 = tmp_path / "a.png"
    f2 = tmp_path / "b.png"
    f1.write_bytes(b"\x89PNG\r\n\x1a\n")
    f2.write_bytes(b"\x89PNG\r\n\x1a\n")

    tool = make_emit_output_tool(
        task_id="task_test_plural_ok",
        output_schema={},
        project_root=str(tmp_path),
    )
    result = tool._run({"file_paths": ["a.png", "b.png"]})
    assert result.startswith("OK"), result
    captured = pop_output("task_test_plural_ok")
    assert captured == {"file_paths": ["a.png", "b.png"]}
