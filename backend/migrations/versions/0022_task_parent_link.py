"""Parent-child link on tasks for Crew v5 fan-out.

Adds two columns to `tasks` so a Crew "parallel step" can fan-out N
child task rows under one parent crew task:

  tasks:
    + parent_task_id      TEXT     FK → tasks.id; NULL = top-level task
    + parent_step_index   INTEGER  which Crew step (sequence index) this
                                    child was dispatched by; NULL until
                                    the parent's runner enters that step

A child task is otherwise a normal task row — same status state machine,
same retry / IO / cleanup paths. The two new fields just tell the
scheduler "don't dispatch me directly; the parent's _fanout_step will".

See state_machine.get_ready_tasks() (filters out parent_task_id non-NULL)
and workflow_svc._run_crew (consumes step.fanout to dispatch children).

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN parent_task_id TEXT")
    op.execute("ALTER TABLE tasks ADD COLUMN parent_step_index INTEGER")
    # Index on parent_task_id — every child lookup goes through this
    # (workflow_svc._run_crew when step.fanout fires, scheduler filter).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id "
        "ON tasks(parent_task_id)"
    )


def downgrade() -> None:
    # SQLite < 3.35 can't DROP COLUMN — no-op (matches sibling migrations).
    pass
