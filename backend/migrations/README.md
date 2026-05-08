# backend/migrations/

Alembic 迁移脚本。

## 用法约定（轻量 Alembic）

- **不开 autogenerate**（autogenerate 是为 SQLAlchemy ORM 设计的，我们不引 ORM 模型层）
- **手写 `op.execute()` 写原生 SQL**
- **每个 migration 必须实现 `downgrade()` 函数**（CI 验证 upgrade head → downgrade -1 → upgrade head 三联回环）

## 目录结构

```
migrations/
├─ env.py            # Alembic 环境配置
├─ script.py.mako    # 新 migration 模板
├─ versions/         # 迁移文件（{rev}_{slug}.py）
│  └─ 0001_baseline.py
└─ sql/              # （可选）独立 SQL 文件，env.py 加载执行
```

## 创建新 migration

```bash
cd backend
alembic revision -m "add_task_kind_column"
# → 生成 versions/{rev}_add_task_kind_column.py
# 手写 upgrade() 和 downgrade()
```

## 执行

- 启动时自动 `alembic upgrade head`（在 lifespan STEP 2）
- 手动：`alembic upgrade head` / `alembic downgrade -1`

## CI 验证

`scripts/test-migration.sh`（Phase 1 创建）：
```
alembic upgrade head
alembic downgrade -1
alembic upgrade head
# 验证 schema 一致
```

## 首个 baseline migration（Phase 1）

包含所有表的初始 DDL（见 plan §4 数据架构）：
- projects / tasks / inception_sessions / inception_messages
- agents / crews / tools / mcp_servers
- llm_providers / llm_models / app_settings
- permissions / chat_sessions / chat_messages / logs / prompt_audit
