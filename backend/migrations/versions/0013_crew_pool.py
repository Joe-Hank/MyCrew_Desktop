"""PM v4: extend crews + tasks for Crew-Native execution.

Adds:
  crews.applicable_scenarios TEXT
      Free-form Chinese text Phase 5 reads to match a task → Crew.
      e.g. "2D sprite / 概念图 / UI 图 / 任何 PNG 图像资源".

  crews.agent_sequence TEXT (JSON)
      Ordered list of [{role, agent_id, step_instructions, progress_template}]
      describing the head → executor(s) → QA chain. Replaces the
      free-form agent_ids list for v4 Crews; legacy agent_ids stays for
      compatibility with anything still reading it.

  tasks.performer_kind TEXT     -- 'agent' | 'crew'
  tasks.performer_id   TEXT     -- FK by id, no constraint (lookup is by table)
      Two-column form chosen over a JSON {kind, id} blob so the planner
      and workflow_svc can filter tasks without json_extract gymnastics.
      Old `agent_id` column is preserved for iterate_existing (PM v3
      legacy flow) — workflow_svc.dispatch reads performer_kind first
      and falls back to agent_id when it's null.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE crews ADD COLUMN applicable_scenarios TEXT")
    op.execute("ALTER TABLE crews ADD COLUMN agent_sequence TEXT")
    op.execute("ALTER TABLE tasks ADD COLUMN performer_kind TEXT")
    op.execute("ALTER TABLE tasks ADD COLUMN performer_id TEXT")


def downgrade() -> None:
    # SQLite < 3.35 cannot DROP COLUMN. No-op.
    pass
