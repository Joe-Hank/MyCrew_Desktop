"""Add session activity tracking + user-renameable title.

Enables the redesigned HistoryDropdown:
  - last_activity_at: ISO ts updated by router after every dispatch, used
    for ORDER BY in `list_sessions`. NULL on legacy rows; the query
    coalesces with created_at as fallback.
  - title: user-supplied label; NULL means "use project_name → 会话 <id 后6>"
  - ix_inception_sessions_activity: index for the ORDER BY clause

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE inception_sessions ADD COLUMN last_activity_at TEXT")
    op.execute("ALTER TABLE inception_sessions ADD COLUMN title TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_inception_sessions_activity "
        "ON inception_sessions(last_activity_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_inception_sessions_activity")
    # SQLite < 3.35 cannot DROP COLUMN; no-op for the column adds.
