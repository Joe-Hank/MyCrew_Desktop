"""Add favorited_at + unfavorited_at columns to projects for the favorites
feature. The list endpoint sorts favorites first (newest favorite at the
left of page 1) and falls back to MAX(unfavorited_at, created_at) for
non-favorites so a project freshly unstarred jumps back to the head of
the non-favorited group, matching what a newly created project does.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite's ALTER TABLE ADD COLUMN is fine for NULL-able columns without
    # defaults — that matches what we want (both columns start NULL).
    op.execute("ALTER TABLE projects ADD COLUMN favorited_at TEXT")
    op.execute("ALTER TABLE projects ADD COLUMN unfavorited_at TEXT")
    # Speeds up the home page's ORDER BY ... LIMIT pagination once a few
    # dozen projects exist.
    op.execute("CREATE INDEX IF NOT EXISTS idx_projects_favorited_at ON projects(favorited_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_projects_favorited_at")
    # SQLite < 3.35 cannot DROP COLUMN. The dev DB is recreated from
    # migrations anyway, so a downgrade just leaves the columns in place.
    # Nothing else to do.
