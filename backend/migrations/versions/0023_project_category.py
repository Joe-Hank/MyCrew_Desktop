"""Project / Agent / Crew category — multi-scenario foundation.

Adds `category` discriminator so the home page can filter projects by
scenario (Unity / AI 视频 / PPT 视频 / ...), and the team page can show
only the agents and crews that belong to the current scenario. Before
this, the project type was inferred client-side from `template_id`
prefix (a brittle hack added 2026-05-21 alongside the home toggle).

Schema
------
- `projects.category`   TEXT NOT NULL DEFAULT 'unity'
- `agents.categories`   TEXT NOT NULL DEFAULT '["unity"]'  (JSON array)
- `crews.category`      TEXT NOT NULL DEFAULT 'unity'

Why agents is an array but crews is single
------------------------------------------
A Crew (e.g. 系统实现组) is scenario-specific by design — each Crew
encodes a domain workflow. Reusing one Crew across categories would
violate the isolation principle we're setting up here. Single column.

An Agent (e.g. QA Engineer, Debugger) is often cross-cutting — same
role can validate Unity code AND AI 视频 scripts AND PPT decks. JSON
array lets us tag one agent row with multiple categories without
duplicating it.

All defaults map existing rows to 'unity' — historical projects and the
8 seeded Crews stay in the Unity bucket, no migration needed for legacy
data. New categories (ai_video / ppt) explicitly set their category on
seed.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # projects.category — single value; the home toggle filters by this.
    op.execute(
        "ALTER TABLE projects ADD COLUMN category TEXT NOT NULL "
        "DEFAULT 'unity'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_category "
        "ON projects(category)"
    )

    # agents.categories — JSON array; cross-cutting roles tag multi.
    op.execute(
        "ALTER TABLE agents ADD COLUMN categories TEXT NOT NULL "
        "DEFAULT '[\"unity\"]'"
    )

    # crews.category — single value; each Crew belongs to one scenario.
    op.execute(
        "ALTER TABLE crews ADD COLUMN category TEXT NOT NULL "
        "DEFAULT 'unity'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_crews_category "
        "ON crews(category)"
    )


def downgrade() -> None:
    # SQLite < 3.35 can't DROP COLUMN — no-op (matches sibling migrations).
    pass
