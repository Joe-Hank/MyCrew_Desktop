# backend/infra/repo/

数据仓储 Adapter 实现（Repository pattern）。

## 文件清单（Phase 1+ 落地）

| 文件 | 实现的 Port |
|---|---|
| `sqlite_repo.py` | 各实体 RepoPort 的 SQLite 实现（用 aiosqlite + 显式 SQL） |
| `file_repo.py` | 文件型大对象（IO json/md、DAG json）的读写抽象 |
| `connection.py` | aiosqlite 连接池、事务上下文 |
| `mappers.py` | DB row ↔ 领域类型转换（字段名差异、JSON 字段反序列化） |

## 关键约束

- **不引入 ORM 模型类**（避免 SQLAlchemy 全套）
- SQL 用 f-string 拼是禁止的；参数走绑定（防注入）
- 长 SQL 用 SQL 模板文件（`backend/migrations/sql/`）或 sqlc 生成

## 写入策略（性能）

- 关键状态（task.status / project.state）→ 同步落库，先 commit 再发事件
- 高频更新（task.progress %）→ 节流写库（每 2s 或 5% 变化）；内存里始终最新值通过 WS 推送
- 文件型大对象（IO）→ 不入 DB，存 `output/`，DB 只存路径引用

## 测试

- 用内存 SQLite（`:memory:`）做集成测试
- Repo 接口在测试中直接用真实 SQLite，不 Mock；上层 Mock 的是 RepoPort 接口
