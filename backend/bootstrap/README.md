# backend/bootstrap/

应用装配层：DI 容器、路径管理、FastAPI app 装配、入口。

## 文件清单（Phase 0/1 创建）

| 文件 | 职责 |
|---|---|
| `main.py` | uvicorn 入口；解析 CLI（`--port` `--token`）；启动健康检查 |
| `app.py` | FastAPI app 工厂：lifespan（启动加载顺序 §14.2）、cors（loopback only）、router 注册、中间件 |
| `container.py` | DI 容器（手写）：注册 ports、infra Adapter、services；启动时构造依赖图，运行时通过 `app.state.container.get(Port)` 拿实例 |
| `paths.py` | 路径常量集中处理：data/、output/、src/tools/、应用根 |
| `secret_client.py` | 通过 loopback HTTP + 一次性 token 从 Tauri Stronghold 拉凭证；实现 `SecretPort` |
| `lifespan.py` | FastAPI lifespan：STEP 1~6 启动加载（详见 plan §14.2）；shutdown 协议 |

## 启动加载顺序（plan §14.2）

1. 加载 `data/config/app.yaml`
2. 初始化 SQLite + 跑 Alembic 迁移
3. 加载所有静态配置（llm_providers / mcp_servers / agents / crews / tools / permissions）
4. 扫描 `src/tools/` 注册用户插件
5. 检查 `data/runtime/last_state.json` → WS 发 `lifecycle.recovery_prompt`
6. 按 app.yaml 的"上次活动 MCP 列表"自动启动 MCP 池

## DI 容器约定

- 容器是单例，挂在 `app.state.container`
- 服务/Adapter 用构造器注入（不靠全局变量）
- 测试时构造一个 test container 注入 Mock Port

## 健康检查

- `GET /healthz` → `{ ok: true, port: 18321, version: ... }`
- Tauri 主进程握手时调用此端点确认 sidecar 就绪
