"""Add experiences table for CrewAI long-term memory (ExperiencePort impl).

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS experiences (
            id          TEXT PRIMARY KEY,
            agent_id    TEXT NOT NULL,
            task_id     TEXT,
            project_id  TEXT,
            tags        TEXT NOT NULL DEFAULT '[]',
            content     TEXT NOT NULL,
            embedding   BLOB,
            score       REAL NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_exp_agent_id ON experiences(agent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_exp_task_id ON experiences(task_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_exp_project_id ON experiences(project_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_exp_agent_id")
    op.execute("DROP INDEX IF EXISTS idx_exp_task_id")
    op.execute("DROP INDEX IF EXISTS idx_exp_project_id")
    op.execute("DROP TABLE IF EXISTS experiences")
