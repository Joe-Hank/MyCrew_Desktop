# backend/models/

Pydantic DTO + 数据库模型。

## 文件清单

| 文件 | 内容 |
|---|---|
| `schemas.py` | Pydantic v2 模型：API 请求/响应 DTO、WS 事件 payload、领域类型 |
| `db_models.py` | 数据库表的 Pydantic 镜像（用于 Repo 反序列化）；不引入 SQLAlchemy ORM |
| `enums.py` | 共用枚举：ProjectState、TaskStatus、TaskKind、ExecutionKind、LlmType、Transport 等 |

## 与 frontend/src/types/ 的同步

- Pydantic 模型导出到 `backend/scripts/export_schema.py`
- 前端通过 `pnpm gen-types` 从 OpenAPI JSON 生成对应 TS 类型
- 这保证前后端类型 single source of truth

## DTO vs DB Model 分离

- DTO（API 边界）可能包含计算字段（如 progress_pct 由 status 派生）
- DB Model（数据库层）严格映射表结构
- mapper（在 `infra/repo/mappers.py`）双向转换

## 设计约束

- Pydantic 模型不写业务方法；只是数据壳
- 业务方法放 `domain/` 或 `services/`
- 字段名与 DB 列名尽量一致（避免 mapper 太复杂）
