"""Add mcp_servers.template_id + .template_values for Strategy C
(template-driven MCP configuration).

template_id   — stable string from services/mcp_templates.TEMPLATES
                (e.g. "figma", "git", "unity_http"). NULL for legacy
                rows until the one-time backfill in app startup tags
                them, or for rows the user picked "custom" for.

template_values — JSON dict of user-supplied field values
                  ({"api_key": "tvly-…", "repository": "F:\\Foo"}).
                  Persisted so the edit form can re-render the same
                  fields without re-deriving from command/args/env_ref.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE mcp_servers ADD COLUMN template_id TEXT")
    op.execute("ALTER TABLE mcp_servers ADD COLUMN template_values TEXT")


def downgrade() -> None:
    # SQLite < 3.35 can't DROP COLUMN — no-op.
    pass
