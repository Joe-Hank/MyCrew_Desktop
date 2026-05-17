"""Guard llm_models.supports_thinking column.

The column was originally added in the 0001 baseline, but some legacy
DBs (early-Phase installs that ran an even earlier baseline before the
column existed) may still be missing it. Defensive idempotent ALTER:
introspect the table; only ADD COLUMN when absent. SQLite doesn't
support `ADD COLUMN IF NOT EXISTS` natively, so the introspection is
done via PRAGMA table_info.

This migration is paired with backend feature work that turns the
thinking-mode toggle in the Agent / LLM editors from a stub into a
real capability gate. The probe route `/llm/probe-thinking` writes
back into this column as a cache.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def upgrade() -> None:
    if not _column_exists("llm_models", "supports_thinking"):
        op.execute(
            "ALTER TABLE llm_models ADD COLUMN "
            "supports_thinking INTEGER NOT NULL DEFAULT 0"
        )


def downgrade() -> None:
    # SQLite < 3.35 cannot DROP COLUMN; leave as-is.
    pass
