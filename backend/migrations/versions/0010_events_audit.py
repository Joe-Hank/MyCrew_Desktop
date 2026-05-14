"""Persistent event log for future AI brain + present-day debugging.

Everything that flows through `WsManager.broadcast` (agent.output,
tool.invoked, inception.message, project.state.changed etc.) is now
also INSERT'd into this table. Same for HTTP mutations (POST/PUT/DELETE
audited via FastAPI middleware → event_type='api.mutation').

This is the audit substrate the future Core AI ("Brain") will read to
understand what's happened in the system; in the short term, the
frontend LogDrawer also uses it to show history beyond the live WS feed.

Auto-truncation policy (enforced by services.events_svc.cleanup_old_events):
  - global max age: 30 days
  - per-project max: 10000 rows (keep newest)

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT,
            project_id TEXT,
            task_id TEXT,
            session_id TEXT,
            payload TEXT,
            created_at INTEGER NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_events_ts ON events(ts DESC)")
    op.execute("CREATE INDEX ix_events_project_ts ON events(project_id, ts DESC)")
    op.execute("CREATE INDEX ix_events_type_ts ON events(event_type, ts DESC)")
    op.execute("CREATE INDEX ix_events_created ON events(created_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_created")
    op.execute("DROP INDEX IF EXISTS ix_events_type_ts")
    op.execute("DROP INDEX IF EXISTS ix_events_project_ts")
    op.execute("DROP INDEX IF EXISTS ix_events_ts")
    op.execute("DROP TABLE IF EXISTS events")
