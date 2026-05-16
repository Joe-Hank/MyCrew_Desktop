# `mycrew-export-mcp` — MCP Server 设计草案

> 目的：让 MyCrew 把自身能力（项目编排、Crew 执行、审计查询）以 MCP 协议暴露给**外部 Agent / IDE / 工具链**。
> 优先级：D 级（不在 Phase 1/2 紧急范围；本文件记录设计 + 现在该做的准备工作）。
> 当前状态：**设计完成；准备工作清单已列；具体实现待用户触发**。

---

## 当前应执行的准备工作（**本轮要做的事**）

> 以下三件事**可以在不实现 MCP server 的前提下做完**，做完之后未来要拉起 export server 是"加一个目录"的工作量，反之就是"改 5 处分散在 services/ 的代码"的工作量。

### ✅ 准备工作 1：审计 actor 字段已能区分调用源（已就绪）

**事实**：`events.actor` 列存在（`backend/migrations/versions/0010_events_audit.py`），但所有现有路径都写 `"system"` 或 `"user"`。

**该做**：在 `services/events_svc.py` 的 `record_event(actor: str)` 默认值改成 `None`，并在调用方显式传 actor。本轮**不必动代码**，但**规则要在评审里立住**：未来加来源时不能再默认 `"system"`。

**已记录在**：`docs/iterations/2026-05-16/architecture-audit.md` 维度 9 的"接入安全要点"。

### ✅ 准备工作 2：`permission_kind` 预留 `external_agent_call`

**该做**：本轮不动代码；下次加 migration 时把 `permissions` 表 seed 一条 `(kind='external_agent_call', pattern='*', allowed=0)`。**默认禁用**，用户必须在设置页显式打开。

**为什么现在不加 migration**：单个 INSERT 不值得专门发一版 migration；下次结构调整顺手做。

### ✅ 准备工作 3：把 `_validate_assignments` 风格的"二次校验"模式提炼成可复用 helper

**事实**：PM v4 Phase 5 已经用了这个模式（`_planner_orchestrator._validate_assignments`），把 LLM 返回的 id 跟"live pool"做交集校验。

**该做**：当未来 export server 要让外部 Agent 调 `invoke_crew(crew_id, …)`，**必须**用同样的模式校验 crew_id 在白名单内。本轮**不抽 helper**（only one caller now），但记下"出现第 2 个 caller 时立刻抽"。

---

## 设计

### 用途场景

| 场景 | 调用方 | 示例 |
|---|---|---|
| 外部 IDE（VSCode/Cursor）查看正在跑的 MyCrew 项目 | `mcp-cli` / IDE extension | `list_projects` → `get_task_status` 监控进度 |
| 第三方 Agent 框架（OpenClaw / AutoGen / 自家脚本）触发 MyCrew Crew | 外部 Python 进程 | `invoke_crew(crew_id="crew_art", task_input={...})` |
| 跨工具的统一审计后台 | 内部运维 | `query_events(filters)` 拉日志聚合 |

### 进程模型

**首选 stdio**（受限 subprocess，安全易控）：
```
父进程（外部 Agent）─┬─ stdin/stdout (JSON-RPC over stdio) ──┐
                                                                ├─ mycrew-export-mcp 子进程
父进程发请求 ────────────────────────────────────────────────────┘
                                              ↓ 调用 MyCrew 内部 services
                                              ↓ 走 GuardedLocalTool 链
                                              ↓ 落 events.actor='external_agent_*'
```

**HTTP 模式**作为第二阶段（多客户端 / 跨机器场景）：
```
外部 Agent ──HTTPS──> mycrew-export-mcp:8091 ──> MyCrew services
                       ↑ Bearer token auth
                       ↑ rate-limit 60 req/min/token
```

### 暴露的工具（Tools）

| 工具 | 入参 | 出参 | 权限要求 |
|---|---|---|---|
| `list_projects()` | — | `[{id, name, state}]` | `external_agent_call` |
| `create_project(name, root_path, execution_kind?)` | 项目基本字段 | `{project_id}` | `external_agent_call` + `dir_create`（root_path） |
| `invoke_crew(crew_id, task_input)` | crew 必须在白名单 | `{task_id, status}` | `external_agent_call` + `cmd_exec` |
| `get_task_status(task_id)` | task_id | `{status, progress, last_error}` | `external_agent_call` |
| `pause_project(project_id)` | project_id | `{state}` | `external_agent_call` |
| `query_events(filters: {actor?, event_type?, since?, project_id?})` | 过滤条件 | `[event]` | `external_agent_call`（read-only） |

### 暴露的资源（Resources）

| URI | 内容 | MIME |
|---|---|---|
| `mycrew://projects/{id}/blueprint` | 项目蓝图 JSON | application/json |
| `mycrew://projects/{id}/tasks/{tid}/io` | 任务 IO（含 PM v4 sub-step） | application/json |
| `mycrew://tools/registry` | 全部可用工具元数据 | application/json |
| `mycrew://crews/{id}` | Crew 序列定义 | application/json |

### 暴露的 Prompts

| 名称 | 用途 | 模板变量 |
|---|---|---|
| `/crew_pool_summary` | 内嵌 list_performers 输出 | 无 |
| `/project_audit` | 当前项目健康检查 | `project_id` |

### 后端代码布局（建议）

```
backend/
├── mcp_export/                  # 新模块，本文设计的核心
│   ├── __init__.py
│   ├── server.py                # MCP server 主循环 (stdio/http)
│   ├── tools.py                 # 6 个工具，每个委托给现有 *_svc.py
│   ├── resources.py             # 4 个 read-only 资源
│   ├── prompts.py               # 2 个 prompt 模板
│   └── auth.py                  # token 验证 + permission 检查
└── bootstrap/
    └── app.py                   # 加一个 STEP X：可选启动 export server 子进程
                                 #   控制变量：env MYCREW_EXPORT_MCP=1（默认关）
```

### 安全要点（**必读，落地时不能漏**）

1. **每个工具调用前**：`await require_permission("external_agent_call")`，缺该开关一律 deny。
2. **`actor` 字段**：必须写真实调用源（`"openclaw:<session_id>"` / `"vscode:<workspace>"`），不能写 `"system"`。
3. **`invoke_crew` 二次校验**：crew_id 必须在 DB `crews` 表 + `is_auto_generated=0` 内（仿 Phase 5 `_validate_assignments`），杜绝调用临时 crew。
4. **stdio 子进程隔离**：mycrew-export-mcp 不直接共享 MyCrew 主进程的 `WorkflowService._active`；它通过 HTTP 内部调主进程暴露的 `/api/v1/workflow/*`，避免跨进程状态污染。
5. **频次限制**：单 token 60 req/min（用 `infra/rate_limit.py`，待实现）。
6. **审计 watchdog**：每 5 分钟统计 `events` 表里 `actor LIKE '%external_agent%'` 的调用频次，超阈值告警。

### 回滚预案

- `MYCREW_EXPORT_MCP=0`（默认）→ 下次启动不拉起子进程，MyCrew 内部行为完全不受影响。
- 出问题就把 env 关掉、写 incident、修完再开。

### 测试要求

落地前必须有 1 个端到端测试：
1. 启动 export server（stdio mode）。
2. 测试客户端调 `list_projects` → 返回非空 list。
3. 测试客户端调 `invoke_crew` 用一个**伪造的 crew_id** → 应被拒绝（permission 或 not-in-pool）。
4. 测试客户端调 `query_events(filters={'actor': 'external_agent_test'})` → 返回前面两步的审计记录。

---

## 工作量估算

| 阶段 | 工作量 | 触发条件 |
|---|---|---|
| 设计（本文档） | 已完成 | — |
| Phase A：stdio mode 最小实现（list_projects + query_events 两个工具） | 2 天 | 用户决定接 OpenClaw 等外部 Agent 时 |
| Phase B：剩余 4 个工具 + 4 个资源 + 2 个 prompt | 3 天 | 同上 |
| Phase C：HTTP mode + token auth + rate limit | 2 天 | 出现"多客户端访问"需求时 |
| 端到端测试 + 文档 | 1 天 | 每个 Phase 末尾 |

**触发不动**：没有"我要让 X 调 MyCrew"的具体需求前，不要为了未来 demo 而提前实现。

---

## 与现有模块的关系

| 现有模块 | 新模块如何借用 |
|---|---|
| `permission_guard.require_permission` | 工具调用前必经，新增 `external_agent_call` kind |
| `GuardedLocalTool` 基类 | 不强制继承（MCP 协议本身就是 wrap 层），但**审计**走同样的 `tool.invoked` 事件 |
| `services/events_svc.record_event` | 工具调用、资源读取都用 `actor=` 写审计 |
| `services/workflow_svc.start / pause / retry` | invoke_crew/pause_project 直接走它们（受益于本轮 P1.2 的 asyncio.Lock） |
| `services/project_svc.create_project_with_tasks` | create_project 直接走它（受益于本轮 P1.3 的补偿事务） |
| `infra/repo/crud` | 不直接暴露；外部 Agent 一律走 `*_svc` 抽象，绕不过 |

→ 当前 Phase 1/2 修过的代码**都是 export server 的依赖**。这意味着我们已经隐式地为 export server 打好了 SQL 防注入、并发安全、事务完整性的地基。
