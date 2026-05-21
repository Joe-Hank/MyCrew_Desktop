"""Templates table — formalises per-scenario project templates.

Replaces the previously-hardcoded `TEMPLATE_ID_TO_DIR` dict in
`services/template_cloner_svc.py`. Each template binds:
  - a category (which scenario it belongs to)
  - a scaffold strategy (how to lay down the project workspace)
  - a default Crew set (which Crews this template auto-pre-loads)
  - an inception prompt id (which PM prompt chain to invoke)

Why this needs to be a table not a dict
---------------------------------------
With multiple scenarios, the template list will grow and diverge per
category. A dict in code means seed_crews / inception_svc / project_svc
all import it; adding a category needs a coordinated multi-file edit.
A table lets each category seed its own templates independently on
backend boot — no cross-category file mutation.

Scaffold strategies
-------------------
- `git_clone`     : clone a sub-directory from a GitHub template repo
                    (current Unity behaviour; scaffold_config carries
                    repo URL + sub_dir)
- `local_mkdir`   : create an empty directory tree locally
                    (for AI 视频 / PPT scenarios; scaffold_config
                    carries the dir layout JSON)
- `no_scaffold`   : no workspace setup; project_root stays NULL
                    (pure-text scenarios with no file output)

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            scaffold_strategy TEXT NOT NULL,
            scaffold_config TEXT,
            inception_prompt_id TEXT,
            seed_crew_names TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_templates_category "
        "ON templates(category)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS templates")
