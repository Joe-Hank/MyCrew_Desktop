"""Add tasks.code_contract — V5 named-symbol contract.

PM v5 inserts a new "Code Contract Designer" phase between Phase 4
(project_mgmt) and the renumbered Phase 6 (agent_assignment). The new
phase walks all tasks that produce .cs files and writes a per-task
contract listing the public classes / methods / events / fields the
generated code must contain plus the upstream symbols each task may
import. Crew Head cannot mutate this; Crew QA verifies regex-match
against generated .cs and fails the task otherwise.

Column shape: TEXT holding the JSON serialization of CodeContract
(see _planner_models.CodeContract). NULL = "this task produces no .cs
files, no contract" (Art / Audio / pure-prefab tasks). Empty JSON
object {} is reserved for "contract was attempted but came back
empty" and is treated as NULL by Crew QA.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN code_contract TEXT")


def downgrade() -> None:
    # SQLite < 3.35 cannot DROP COLUMN. No-op.
    pass
