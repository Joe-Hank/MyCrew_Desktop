"""Add tasks.failure_analysis + tasks.failure_analysis_at.

When a task ends in failed / validation_failed, a dedicated LLM
(failure_analyzer) is invoked once to write a concise diagnosis the
user can read directly from the task card — no chat back-and-forth.
The two columns persist the LLM output (markdown text) and the time
it was computed. NULL means "no analysis yet" (still in flight, or
healthy task that never failed).

Replaces the prior pattern where users had to open AgentChatDrawer
and ask the diagnostic agent "why did this fail" — that round-trip
is now precomputed and the drawer just renders it. The old chat path
is kept around (task_guidance.py + AgentChatDrawer.tsx) as a fallback
in case we need to roll back.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN failure_analysis TEXT")
    op.execute("ALTER TABLE tasks ADD COLUMN failure_analysis_at TEXT")


def downgrade() -> None:
    # SQLite < 3.35 cannot DROP COLUMN. No-op.
    pass
