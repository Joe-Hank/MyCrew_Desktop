# backend/api/

接入层：REST 路由 + WebSocket Hub。

## 关键约束

- **不写业务逻辑**：路由只做参数校验、调用 service、包装响应
- **统一响应格式**：`{ ok: true, data }` 或 `{ ok: false, error: { code, message } }`
- **本地监听**：仅 loopback（127.0.0.1），不暴露公网

## 文件清单（Phase 1+ 落地）

| 文件 | 端点前缀 | 关键端点 |
|---|---|---|
| `routes_project.py` | `/projects` | CRUD、`/clone`、`/start`、`/pause`、`/resume`、`/root-path` |
| `routes_task.py` | `/tasks` | CRUD、`/pause`、`/rerun`、`/io`、`/intervene` |
| `routes_inception.py` | `/inceptions` | 开会话、`/messages`（SSE 流）、`/index-path`、`/finalize` |
| `routes_mcp.py` | `/mcp` | `/servers` CRUD、`/servers/:id/restart`、`/refresh-all`、`/internal/call`（loopback only） |
| `routes_llm.py` | `/llm` | `/providers` CRUD、`/quota` |
| `routes_agent.py` | `/agents` `/crews` `/tools` | CRUD、`/tools/scan` |
| `routes_config.py` | `/config` `/permissions` `/app_settings` | GET/PUT |
| `routes_log.py` | `/logs` | 查询带 source/level/since 过滤 |
| `routes_lifecycle.py` | `/lifecycle` | `/state`（关闭前状态查询）、`/pause-all`（shutdown sequence step） |
| `ws.py` | `/ws` | WebSocket Hub：消息分发 + `prompt.request/response` 双向 |

## 鉴权

- 仅 loopback：默认信任
- `/mcp/internal/call` 等内部端点额外要求一次性 token（在 sidecar 启动时由 Tauri 传入）

## OpenAPI

- FastAPI 自动生成 `/openapi.json` → 前端类型生成
- `/docs` 在 dev 模式下开启（生产关闭）
