"""Smoke test for crud.py SQL-fragment guards (P0 fix in audit 2026-05-16).

These tests exercise the validators directly (no DB) — they ensure the
shape checks reject obvious injection attempts without depending on
sqlite execution.
"""
from __future__ import annotations

import pytest

from infra.repo.crud import (
    SqlFragmentError,
    _validate_table,
    _validate_where,
    _validate_order_by,
)


# ── Table name ────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["tasks", "task_events", "_priv", "T1"])
def test_table_accepts_identifiers(name):
    _validate_table(name)  # no raise


@pytest.mark.parametrize("name", [
    "tasks; DROP TABLE projects",
    "tasks WHERE 1=1",
    "tasks--comment",
    "tasks/*nope*/",
    "tasks ;",
    "1tasks",
    "",
    "tasks bobby",
])
def test_table_rejects_anything_non_identifier(name):
    with pytest.raises(SqlFragmentError):
        _validate_table(name)


# ── WHERE clause ──────────────────────────────────────────────────

def test_where_empty_is_ok():
    _validate_where("", ())


def test_where_param_count_must_match():
    _validate_where("project_id = ?", ("p1",))  # ok
    with pytest.raises(SqlFragmentError, match="placeholders"):
        _validate_where("project_id = ?", ())
    with pytest.raises(SqlFragmentError, match="placeholders"):
        _validate_where("project_id = ?", ("p1", "p2"))


@pytest.mark.parametrize("clause", [
    "project_id = ? OR 1=1; DROP TABLE projects",
    "1=1 --",
    "x = ? /*",
    "x = ?\x00",
])
def test_where_rejects_dangerous_substrings(clause):
    with pytest.raises(SqlFragmentError):
        _validate_where(clause, ("p",) * clause.count("?"))


def test_where_accepts_real_world_callers():
    # These are existing callers from services/*.py — must all pass.
    _validate_where("project_id = ?", ("p1",))
    _validate_where(
        "project_id = ? AND status = ?", ("p1", "running"),
    )
    _validate_where(
        "project_id = ? AND status NOT IN ('done','failed','aborted','validation_failed')",
        ("p1",),
    )
    _validate_where("role = ? AND is_auto_generated = 0", ("Art Director",))
    _validate_where("model_name LIKE ?", ("%deepseek%flash%",))


# ── ORDER BY ──────────────────────────────────────────────────────

@pytest.mark.parametrize("ob", [
    "created_at DESC",
    "name",
    "name ASC, created_at DESC",
    "id",
])
def test_order_by_accepts_safe_forms(ob):
    _validate_order_by(ob)


@pytest.mark.parametrize("ob", [
    "(SELECT 1)",
    "name; DROP TABLE projects",
    "name --hidden",
    "name/*",
    "1",  # plain number isn't an identifier
    "name FOO",  # FOO is not ASC/DESC
])
def test_order_by_rejects_anything_else(ob):
    with pytest.raises(SqlFragmentError):
        _validate_order_by(ob)
