"""Baseline schema — all tables from plan §4

Revision ID: 0001
Revises:
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            root_path   TEXT,
            state       TEXT NOT NULL DEFAULT 'ready',
            is_running  INTEGER NOT NULL DEFAULT 0,
            progress_pct REAL NOT NULL DEFAULT 0,
            execution_kind TEXT NOT NULL DEFAULT 'sequential',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            copied_from TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS inception_sessions (
            id            TEXT PRIMARY KEY,
            project_id    TEXT,
            llm_id        TEXT,
            thinking_mode INTEGER NOT NULL DEFAULT 0,
            system_prompt TEXT,
            indexed_paths TEXT DEFAULT '[]',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS inception_messages (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            ts         TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES inception_sessions(id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS llm_providers (
            id       TEXT PRIMARY KEY,
            name     TEXT NOT NULL,
            type     TEXT NOT NULL,
            api_key_ref TEXT,
            base_url TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS llm_models (
            id            TEXT PRIMARY KEY,
            provider_id   TEXT NOT NULL,
            model_name    TEXT NOT NULL,
            label         TEXT,
            max_tokens    INTEGER,
            supports_thinking INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (provider_id) REFERENCES llm_providers(id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id               TEXT PRIMARY KEY,
            role             TEXT NOT NULL,
            goal             TEXT,
            backstory        TEXT,
            reasoning        INTEGER NOT NULL DEFAULT 0,
            max_retry        INTEGER NOT NULL DEFAULT 3,
            memory_enabled   INTEGER NOT NULL DEFAULT 0,
            memory_path      TEXT,
            thinking_mode    INTEGER NOT NULL DEFAULT 0,
            tool_ids         TEXT DEFAULT '[]',
            llm_id           TEXT,
            is_auto_generated INTEGER NOT NULL DEFAULT 0,
            promoted_at      TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS crews (
            id               TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            process          TEXT NOT NULL DEFAULT 'sequential',
            agent_ids        TEXT DEFAULT '[]',
            is_auto_generated INTEGER NOT NULL DEFAULT 0,
            promoted_at      TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS tools (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            script_path  TEXT,
            source       TEXT NOT NULL DEFAULT 'user',
            checksum     TEXT,
            params_schema TEXT DEFAULT '{}'
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id            TEXT PRIMARY KEY,
            project_id    TEXT NOT NULL,
            title         TEXT NOT NULL,
            detail        TEXT,
            agent_id      TEXT,
            kind          TEXT NOT NULL DEFAULT 'regular',
            output_schema TEXT DEFAULT '{}',
            status        TEXT NOT NULL DEFAULT 'pending',
            deps          TEXT DEFAULT '[]',
            io_in_ref     TEXT,
            io_out_ref    TEXT,
            started_at    TEXT,
            finished_at   TEXT,
            qa_score      REAL,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (agent_id) REFERENCES agents(id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS mcp_servers (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            transport       TEXT NOT NULL DEFAULT 'stdio',
            command         TEXT,
            args            TEXT DEFAULT '[]',
            url             TEXT,
            env_ref         TEXT DEFAULT '{}',
            enabled         INTEGER NOT NULL DEFAULT 1,
            auto_start      INTEGER NOT NULL DEFAULT 1,
            timeout         INTEGER NOT NULL DEFAULT 30,
            discovered_tools TEXT DEFAULT '[]'
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            id      TEXT PRIMARY KEY,
            kind    TEXT NOT NULL,
            pattern TEXT,
            allowed INTEGER NOT NULL DEFAULT 1
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id         TEXT PRIMARY KEY,
            task_id    TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            ts         TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         TEXT NOT NULL DEFAULT (datetime('now')),
            level      TEXT NOT NULL DEFAULT 'info',
            source     TEXT NOT NULL DEFAULT 'app',
            project_id TEXT,
            task_id    TEXT,
            event      TEXT,
            message    TEXT,
            request_id TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS prompt_audit (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id    TEXT NOT NULL,
            ctx           TEXT,
            user_response TEXT,
            latency_ms    INTEGER,
            ts            TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Seed default permissions (9 boolean switches, all on)
    op.execute("""
        INSERT OR IGNORE INTO permissions (id, kind, pattern, allowed) VALUES
        ('perm_file_read',    'file_read',    '*', 1),
        ('perm_file_write',   'file_write',   '*', 1),
        ('perm_file_delete',  'file_delete',  '*', 1),
        ('perm_file_modify',  'file_modify',  '*', 1),
        ('perm_folder_read',  'folder_read',  '*', 1),
        ('perm_dir_create',   'dir_create',   '*', 1),
        ('perm_cmd_exec',     'cmd_exec',     '*', 1),
        ('perm_bg_cmd',       'bg_cmd',       '*', 1),
        ('perm_git',          'git',          '*', 1)
    """)


def downgrade() -> None:
    for table in [
        "prompt_audit", "logs", "chat_messages", "chat_sessions",
        "permissions", "app_settings", "mcp_servers", "tasks",
        "tools", "crews", "agents", "llm_models", "llm_providers",
        "inception_messages", "inception_sessions", "projects",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table}")
