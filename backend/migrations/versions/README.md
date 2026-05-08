# backend/migrations/versions/

Alembic 迁移版本文件。

## 命名规范

`{revision_id}_{slug}.py`，例如：
```
0001_baseline.py
0002_add_task_kind.py
0003_add_discovered_tools_to_mcp.py
```

`revision_id` 推荐用 `0001`/`0002` 自增方式（不用 Alembic 默认的 hash），便于人脑追踪顺序。

## 模板

```python
"""baseline schema

Revision ID: 0001
Revises: 
Create Date: 2026-XX-XX
"""
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            ...
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE projects;")
```

## Phase 1 必须落地

- `0001_baseline.py` — 含 plan §4 列出的所有表
- 每张表的列、约束、索引、默认值都对齐 plan §4

## 测试要求

- 每个新 migration 写完后跑 `scripts/test-migration.sh` 验证三联回环
- CI 中 must-pass
