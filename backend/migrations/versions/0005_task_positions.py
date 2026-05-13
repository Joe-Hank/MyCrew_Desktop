"""Add position_x / position_y columns to tasks so the canvas can persist
user-edited layouts. NULL = "never been dragged, use auto layout"; the
frontend falls back to the wave-column layout if either coordinate is NULL.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN position_x REAL")
    op.execute("ALTER TABLE tasks ADD COLUMN position_y REAL")


def downgrade() -> None:
    # SQLite < 3.35 cannot DROP COLUMN. No-op; columns are nullable so the
    # earlier schema is logically reachable.
    pass
