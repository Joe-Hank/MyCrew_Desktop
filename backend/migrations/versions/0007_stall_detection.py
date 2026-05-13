"""Add stall-detection columns: tasks.last_activity_at + app_settings entry
for the timeout threshold.

The watchdog service scans every is_running=1 project periodically. For each
RUNNING task it compares now() to last_activity_at. If the gap exceeds the
stall_timeout_minutes threshold, the task is moved to STALLED and the
project gets auto-paused. Previously a hung LLM call or a wedged MCP server
would leave the project state stuck at `running` indefinitely.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
# 0006 doesn't exist yet — chain to 0005 directly. When 0006 lands later,
# this revision's down_revision will need a rebase.
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN last_activity_at TEXT")
    op.execute(
        "INSERT OR IGNORE INTO app_settings (key, value) "
        "VALUES ('stall_timeout_minutes', '20')"
    )


def downgrade() -> None:
    # SQLite < 3.35 cannot DROP COLUMN. No-op.
    op.execute("DELETE FROM app_settings WHERE key = 'stall_timeout_minutes'")
