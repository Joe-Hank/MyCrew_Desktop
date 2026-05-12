"""Add indexes on high-cardinality FK / status columns for query performance.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hot path: workflow_svc._load_tasks (filter by project_id) + status queries
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status)")

    # inception_messages by session
    op.execute("CREATE INDEX IF NOT EXISTS idx_incep_msg_session_id ON inception_messages(session_id)")

    # llm_models by provider
    op.execute("CREATE INDEX IF NOT EXISTS idx_llm_models_provider_id ON llm_models(provider_id)")

    # inception_sessions by project
    op.execute("CREATE INDEX IF NOT EXISTS idx_incep_sessions_project_id ON inception_sessions(project_id)")

    # projects by state (lifecycle queries: recover all RUNNING projects)
    op.execute("CREATE INDEX IF NOT EXISTS idx_projects_state ON projects(state)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tasks_project_id")
    op.execute("DROP INDEX IF EXISTS idx_tasks_status")
    op.execute("DROP INDEX IF EXISTS idx_tasks_project_status")
    op.execute("DROP INDEX IF EXISTS idx_incep_msg_session_id")
    op.execute("DROP INDEX IF EXISTS idx_llm_models_provider_id")
    op.execute("DROP INDEX IF EXISTS idx_incep_sessions_project_id")
    op.execute("DROP INDEX IF EXISTS idx_projects_state")
