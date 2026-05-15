"""Persist a task's last failure message + a coarse category.

`validation_errors` already covers schema-mismatch failures, but every
other class (LLM quota, MCP not connected, network timeout, generic
agent crash) was only broadcast as a transient WS event — gone on
refresh, leaving the task card showing a generic amber "!" with no
explanation.

This migration adds:
  last_error      TEXT  — full exception string (capped client-side)
  last_error_kind TEXT  — one of: quota | mcp | network | validation
                                | stalled | tool | unknown
                          — derived heuristically in workflow_svc and
                            kept here so the frontend can render a
                            short Chinese hint on hover without re-
                            classifying every render.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN last_error TEXT")
    op.execute("ALTER TABLE tasks ADD COLUMN last_error_kind TEXT")


def downgrade() -> None:
    # SQLite < 3.35 cannot DROP COLUMN. No-op.
    pass
