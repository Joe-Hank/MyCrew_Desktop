"""User preferences KV store (initially: dismissible-dialog choices).

A single-user app doesn't need a `users` table, so this is a flat key/value
table holding any UX-level preference that should survive restarts. The
first consumer is the dismissible-dialog framework (Stage A of the
2026-05-16 reliability pass): when the user ticks "不再显示" on a confirm
dialog, the choice is stored here under key `dismissed_dialog.<id>` and
loaded on app start so future prompts auto-resolve.

The shape is deliberately the same as `app_settings` (key/value/timestamp)
but a separate table — app_settings is for global app behavior (compliance
mode, etc.) and user_preferences is for *user* UX choices. Splitting now
saves the "is this row mine?" question later and lets a future export /
reset-preferences action target the right rows.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_preferences")
