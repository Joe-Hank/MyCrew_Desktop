"""Persist validation errors on tasks.

When a task reaches VALIDATION_FAILED, the workflow_svc currently emits a
TaskValidationFailed event but the error list is lost on browser refresh
or backend restart. Users see "validation_failed" with no clue why. This
column stores the raw error strings (JSON-encoded list) so the frontend
can show them in the task drawer / IO viewer.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN validation_errors TEXT")


def downgrade() -> None:
    # SQLite < 3.35 cannot DROP COLUMN. No-op.
    pass
