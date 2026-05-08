# backend/

Python sidecar：FastAPI + Uvicorn。被 Tauri 主进程作为 sidecar spawn。

## 分层架构（强约束）

```
api/          接入层：REST 路由 + WS Hub；只做参数校验与 service 调用
services/     业务层：编排领域逻辑、调度 Port 实现
domain/       领域层：纯业务逻辑、零 IO；通过 Port 抽象与外界交互
ports/        端口层：Protocol 接口（领域/服务通过它依赖）
infra/        数据/集成层：Port 的具体实现（LLM/MCP/SQLite/WS）
bootstrap/    应用装配：DI 容器、路径管理、FastAPI app、入口
models/       Pydantic DTO 与数据库模型
migrations/   Alembic 迁移脚本（仅 op.execute 写原生 SQL，不开 autogenerate）
tests/        单元 + Port Mock 集成测试
```

## 依赖方向（不可逆）

```
api → services → domain
                    ↓
                 ports
                    ↑
              infra（实现 ports）
```

- 领域层不直接 import infra；仅依赖 ports 抽象
- service 通过 DI 容器拿到 Port 实现
- 这保证：替换 infra（如换 LLM provider）不动 domain；测试时 Mock Port

## 入口

`bootstrap/main.py` —— Uvicorn 启动入口（含 `--port` 探测、健康检查端点）

## 关键文件（Phase 0/1 创建）

- `pyproject.toml` `uv.lock`（或 `requirements.txt`）
- `alembic.ini`
- `.python-version`（3.12+）

## 测试

- `pytest backend/tests`：单元 + Port Mock 集成
- 覆盖率目标：核心 services/ 与 domain/ ≥ 70%（见 plan §17.2）
