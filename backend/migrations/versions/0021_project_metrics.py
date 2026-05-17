"""Per-project token / cost / runtime metrics plus model pricing.

Adds the columns the home-page ProjectCard badges need to show
"¥ x.xx · y.yk tok" and "hh:mm:ss" without any runtime aggregation:

  llm_models:
    + input_price_cny_per_1m   INTEGER   (cents per 1M input tokens)
    + output_price_cny_per_1m  INTEGER   (cents per 1M output tokens)

  projects:
    + total_input_tokens       BIGINT    default 0
    + total_output_tokens      BIGINT    default 0
    + total_cost_cents         BIGINT    default 0
    + total_runtime_seconds    INTEGER   default 0
    + runtime_started_at       TEXT      (NULL while not actively running)

  tasks:
    + last_run_started_at      TEXT      (NULL when not running)

  inception_sessions:
    + pending_input_tokens     BIGINT    default 0
    + pending_output_tokens    BIGINT    default 0
    + pending_cost_cents       BIGINT    default 0
    + pending_runtime_seconds  INTEGER   default 0
    + pm_started_at            TEXT

The "pending_*" columns capture PM-phase usage before a project row
exists; they're transferred onto the finalised project's totals by
inception_svc.finalize. After finalize, all increments land on the
project row directly.

Includes a data migration seeding 2026-05 list-price estimates for
well-known models (Claude / GPT / DeepSeek / Qwen / GLM). Users can
edit these in the LLM settings drawer; 0/0 disables billing for that
model entirely.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── 2026-05 list-price estimates (cents per 1M tokens) ───────────────
# Stored as INTEGER cents to avoid floating-point drift on aggregation.
# Patterns are matched with SQL LIKE; first-match wins. Users override
# via /llm/models/<id> PUT — the seed only fires for rows where both
# columns are still NULL (newly added). Existing rows that the user
# manually set keep their values on subsequent runs.
PRICE_SEED: list[tuple[str, int, int]] = [
    # (model_name LIKE pattern, input cents/1M, output cents/1M)
    ("claude-opus-4-7%",            1800, 9000),
    ("claude-opus-4%",              1800, 9000),
    ("claude-3-5-sonnet%",          1800, 9000),
    ("claude-3-7-sonnet%",          1800, 9000),
    ("claude-sonnet-4%",            1800, 9000),
    ("claude-haiku-4-5%",            100,  500),
    ("claude-3-5-haiku%",            100,  500),
    ("claude-haiku%",                100,  500),
    ("gpt-5%",                       500, 2000),
    ("gpt-4o%",                      250, 1000),
    ("gpt-4-turbo%",                1000, 3000),
    ("gpt-4%",                      3000, 6000),
    ("o1%",                         1500, 6000),
    ("o3%",                         1500, 6000),
    ("deepseek-chat%",                50,  100),
    ("deepseek-coder%",               50,  100),
    ("deepseek-v3%",                  50,  100),
    ("deepseek-v4%",                  50,  100),
    ("deepseek-r1%",                  50,  200),
    ("qwen%",                        100,  300),
    ("glm-4%",                        50,  150),
    ("glm-z%",                       100,  300),
]


def upgrade() -> None:
    # llm_models — pricing
    op.execute(
        "ALTER TABLE llm_models ADD COLUMN input_price_cny_per_1m INTEGER"
    )
    op.execute(
        "ALTER TABLE llm_models ADD COLUMN output_price_cny_per_1m INTEGER"
    )

    # projects — cumulative counters + runtime baseline
    op.execute(
        "ALTER TABLE projects ADD COLUMN total_input_tokens INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN total_output_tokens INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN total_cost_cents INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN total_runtime_seconds INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE projects ADD COLUMN runtime_started_at TEXT"
    )

    # tasks — per-run baseline for the "retry adds time" rule
    op.execute(
        "ALTER TABLE tasks ADD COLUMN last_run_started_at TEXT"
    )

    # inception_sessions — pre-finalize PM accumulators
    op.execute(
        "ALTER TABLE inception_sessions "
        "ADD COLUMN pending_input_tokens INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE inception_sessions "
        "ADD COLUMN pending_output_tokens INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE inception_sessions "
        "ADD COLUMN pending_cost_cents INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE inception_sessions "
        "ADD COLUMN pending_runtime_seconds INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE inception_sessions ADD COLUMN pm_started_at TEXT"
    )

    # Data migration — seed list prices for known model patterns.
    # Only updates rows where both columns are NULL (don't trample user edits).
    for pattern, in_cents, out_cents in PRICE_SEED:
        op.execute(
            "UPDATE llm_models SET "
            f"input_price_cny_per_1m = {in_cents}, "
            f"output_price_cny_per_1m = {out_cents} "
            "WHERE input_price_cny_per_1m IS NULL "
            "AND output_price_cny_per_1m IS NULL "
            f"AND LOWER(model_name) LIKE '{pattern}'"
        )


def downgrade() -> None:
    # SQLite < 3.35 can't DROP COLUMN — no-op.
    pass
