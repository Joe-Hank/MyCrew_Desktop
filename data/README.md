# data/

运行时数据。**整个目录被 .gitignore 排除**，不进版本控制。

## 子目录

| 子目录 | 内容 | 写入时机 |
|---|---|---|
| `config/` | 应用配置（`app.yaml` 含主题、窗口尺寸、上次活动等） | UI 操作时 debounce 写 |
| `db/` | SQLite 主库（`mycrew.db`）+ WAL 文件 | 状态变化时 commit |
| `logs/` | 滚动日志（`{YYYYMMDD}.jsonl`） | structlog 实时写 |
| `cache/` | MCP 心跳缓存等临时数据 | 心跳/查询时刷新 |
| `secrets/` | OS Keychain / Stronghold 失败时的 DPAPI 加密回退（`keystore.json`） | 用户保存凭证时 |
| `runtime/` | 运行态快照（`last_state.json`） | shutdown 落盘 + 周期 60s |

## 备份策略（推荐用户层面）

- 用户层面定期备份整个 `data/` 目录
- 凭证 (`secrets/keystore.json`) 与配置 (`config/app.yaml`) 是核心
- DB (`db/mycrew.db`) 是项目历史

## 重置应用

```
# Windows PowerShell
Remove-Item -Recurse -Force data/
# 或
Remove-Item -Recurse -Force data/db/, data/runtime/, data/logs/
```

> 删除 `data/secrets/` 会丢失所有 LLM 凭证，需重新录入。

## 路径常量

后端通过 `bootstrap/paths.py` 集中管理本目录路径，组件不应硬编码字符串路径。

## 与 output/ 的区别

- `data/`：应用配置、运行时状态、日志、缓存（**应用层**数据）
- `output/`：项目运行产物，按 `{YYYYMMDD_HHmm}_{Project}` 分目录（**业务层**产物）
