"""Add projects.scaffold_status + root_parent_path.

V5+ feature (2026-05-17): when a user picks a Unity template, the
project's root_path used to be set to the user-chosen directory
directly. New flow:
  1. User picks template + a *parent* root dir (e.g. F:/UnityProjects).
  2. Persistence stores that parent as `root_parent_path` and marks
     `scaffold_status='pending'`.
  3. First click on "开始项目" triggers backend to:
       - clone the matching subfolder from the Templates Git repo
       - rename it to the project's English name
       - update `root_path` to the new child dir
       - flip `scaffold_status` to 'done'
  4. Subsequent starts skip scaffold; treat root_path as the source of
     truth (the child dir, not the parent).

Why a separate `scaffold_status` rather than overloading `state`:
project state already drives the harness state machine (ready→running→
paused→completed). Scaffolding is a pre-execution step that doesn't fit
cleanly there. A sidecar column keeps the existing state machine
untouched and lets the UI overlay a 「正在构建项目雏形」 progress
indicator without changing legacy semantics.

Both columns default NULL so existing rows are unaffected; non-Unity
projects keep both as NULL forever.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN scaffold_status TEXT")
    op.execute("ALTER TABLE projects ADD COLUMN root_parent_path TEXT")


def downgrade() -> None:
    pass  # SQLite < 3.35 cannot DROP COLUMN
