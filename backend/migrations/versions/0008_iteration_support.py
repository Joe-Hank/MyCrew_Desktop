"""Add iteration-mode columns to projects + template_id to inception_sessions.

Iteration mode = a project that's a follow-up round of an earlier completed
project. The new row's `parent_project_id` references the previous project
(forming an iteration chain), `iteration_index` records the round number
(1 = original, 2 = first iteration, …), and `template_id` snapshots which
Unity template the round started from.

`inception_sessions.template_id` is also added so the inception flow can
remember the user's template pick across multiple chat turns before
create_workflow fires.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN parent_project_id TEXT")
    op.execute("ALTER TABLE projects ADD COLUMN iteration_index INTEGER DEFAULT 1")
    op.execute("ALTER TABLE projects ADD COLUMN template_id TEXT")
    op.execute("ALTER TABLE inception_sessions ADD COLUMN template_id TEXT")
    op.execute("ALTER TABLE inception_sessions ADD COLUMN mode TEXT DEFAULT 'create'")
    # Index helps "show all iterations of X" lookups
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_parent ON projects(parent_project_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_projects_parent")
    # SQLite < 3.35 cannot DROP COLUMN; no-op for the column adds.
