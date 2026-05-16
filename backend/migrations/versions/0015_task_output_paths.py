"""Add tasks.output_paths — PM's explicit must-produce-files contract.

Stage E (2026-05-16): emit_output's path-existence check used to rely on
a hard-coded whitelist of payload field names (`file_path`, `file_paths`,
…). When the PM picked a non-whitelist name (e.g. `generated_files`),
the agent could ship a payload claiming new paths and the check would
silently skip them — task marked done, disk empty.

The fix is a separate contract column populated by the Planner with the
explicit list of files this task must produce. emit_output verifies each
one exists on disk regardless of where (or whether) the agent restated
them in the payload.

Column shape: TEXT holding a JSON array of strings. NULL = no contract
(legacy / iterate / free-form tasks); empty list = "this task produces
no files" (e.g. design-doc tasks). Existing rows stay NULL; the field
is filled going forward by the Planner phases as they're updated.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN output_paths TEXT")


def downgrade() -> None:
    # SQLite < 3.35 cannot DROP COLUMN. No-op.
    pass
