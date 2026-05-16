# MyCrew v3 — 架构文档

> **最后更新**：2026-05-16（PM v4 落地 + Phase 1/2 安全加固完成）
> 本文档是 MyCrew v3 的架构参考手册。设计决策的完整背景与权衡记录在 `docs/ADR/` 目录下。
> 文档分类索引：`docs/README.md` —— spec / iterations / roadmap / archive 四档导航。

---

## 1. 架构总览

采用 **分层架构 + 事件驱动**，单进程组合模型。三层结构：Tauri 主进程（Rust 壳层）、WebView（React 前端）、Python Sidecar（FastAPI 后端）。

```
┌─────────────────────────────────────────────────────────────┐
│  Tauri 主进程 (Rust)                                         │
│  ─ 窗口/托盘/菜单/自动更新/系统集成                              │
│  ─ Python sidecar 生命周期（tauri.conf.json sidecar + Rust    │
│    监听 stdout/exit + 崩溃重启）                              │
│  ─ Tauri Commands：渲染层↔Rust（仅本地能力：选文件/打开外链/    │
│    版本号/凭证存取，不转发业务）                                │
└──────────────┬──────────────────────────────────────────────┘
               │ HTTP/WS (localhost:18321)
┌──────────────▼──────────────────────────────────────────────┐
│  WebView (React + Vite + TS) — Tauri 内嵌                    │
│  ─ 4 页面：主页 / 任务 / 团队 / 设置                            │
│  ─ React Query（服务端态）+ Zustand（UI 态）                   │
│  ─ 单条 WS 长连接 + 事件分发 hook                              │
└──────────────┬──────────────────────────────────────────────┘
               │ HTTP / WebSocket
┌──────────────▼──────────────────────────────────────────────┐
│  Python Sidecar (FastAPI + Uvicorn)                         │
│  ┌──────────── 接入层 (api/) ────────────┐                   │
│  │ REST 路由 + WS Hub + 鉴权(localhost-only) │              │
│  ├──────────── 业务层 (services/) ────────┤                  │
│  │ 工作流编排 / MCP 池 / LLM 网关 / 项目  │                   │
│  ├──────────── 领域层 (domain/) ──────────┤                   │
│  │ Harness 状态机 / QA / 经验             │                   │
│  ├──────────── 端口层 (ports/) ──────────┤                   │
│  │ Repo 抽象 / LLM 抽象 / MCP 抽象 / 交互  │                   │
│  └──────────── 数据层 (infra/) ──────────┘                   │
│    SQLite / 文件系统 / MCP stdio·http / LLM HTTP             │
└─────────────────────────────────────────────────────────────┘
```

### 核心架构原则

- **依赖倒置**：领域层定义 Port（接口），infra 层实现 Adapter；service 通过 Port 调用，便于替换与 Mock。
- **单向事件流**：领域层产出 Domain Event → EventBus → WS Hub 推到前端；前端命令通过 REST 进入 service 层。
- **无人工 input()**：所有交互通过 WS 双向消息（`prompt.request` / `prompt.response`）。详见 [ADR-008](ADR/008-interaction-port.md)。

---

## 2. 模块清单

### 2.1 前端模块（renderer）

| 模块 | 职责 | 关键文件 |
|---|---|---|
| **layout** | 应用骨架：固定宽左导航、内容区、可折叠底部日志栏（多终端 tab） | `AppShell.tsx` `Sidebar.tsx` `LogDrawer.tsx` |
| **page-home** | 主页：项目卡片网格（4×N 分页）、MCP 连接条、Token 监控条、新建项目入口 | `pages/HomePage.tsx` `home/ProjectGrid.tsx` `home/ProjectCard.tsx` |
| **inception** | 建项目半页对话：LLM 二级选择、思考开关、历史会话、文件索引、任务蓝图编辑 | `inception/InceptionDrawer.tsx` `inception/ChatPane.tsx` `inception/TaskBlueprintEditor.tsx` |
| **page-task** | 任务管理：项目信息条、DAG 蓝图、任务节点操作（编辑/暂停/重跑/Agent 对话/IO 查看） | `pages/TaskPage.tsx` `task/Blueprint.tsx` `task/TaskNode.tsx` |
| **page-team** | 团队：三 Tab（Agents / Crews / Tools）+ 半页编辑器 | `pages/TeamPage.tsx` `team/AgentList.tsx` `team/CrewList.tsx` `team/ToolList.tsx` |
| **page-settings** | 设置：三 Tab（LLM / MCP / 系统权限）+ 半页编辑器 | `pages/SettingsPage.tsx` `settings/LlmList.tsx` `settings/McpList.tsx` |
| **stores** | 服务端状态走 React Query；UI 状态走 Zustand | `queries/use*Query.ts` `stores/use*Store.ts` |
| **net** | REST 客户端 + 单例 WS + 事件路由 | `net/api.ts` `net/ws.ts` `hooks/useEvent.ts` |
| **ui-kit** | 通用组件（Modal / Toast / StatusDot / Empty / Skeleton） | `components/ui/*` |

### 2.2 后端模块（backend）

| 层 | 模块 | 职责 |
|---|---|---|
| **api/** | `routes_project.py` `routes_task.py` `routes_mcp.py` `routes_llm.py` `routes_agent.py` `routes_config.py` `routes_log.py` `ws.py` | REST 路由 + WS Hub；只做参数校验与 service 调用 |
| **services/** | `project_svc.py` | 项目 CRUD、复制、删除、卡片分页。`create_project_with_tasks` 用补偿事务（异常时 delete_project 回滚） |
| | `inception_svc.py` | 建项目对话：管理立项会话、调用 LLM 拆解任务、文件索引、执行结构选择 |
| | `workflow_svc.py` | 启动/暂停/恢复 Harness；**per-project asyncio.Lock 串行化** 同 project 的 start/pause/retry；PM v4 起按 `performer_kind` 路由到 `_run_agent` 或 `_run_crew` |
| | `crewai_runner.py` | CrewAI 桥：`run_task_with_crewai`（单 agent）+ `run_crew_step_with_crewai`（PM v4 Crew 单步） |
| | `mcp_svc.py` | MCP 服务器池：启动、心跳、工具列表缓存、全量重连 |
| | `llm_svc.py` | LLM 配置、Token 用量轮询（百分比/M 数/可用性三态） |
| | `agent_svc.py` | Agent 模板 CRUD：角色/目标/能力/工具绑定 |
| | `crew_svc.py` | Crew CRUD：队名/过程/`agent_sequence`(JSON head→executors→QA)/`applicable_scenarios` |
| | `tool_svc.py` | Tool CRUD：扫描 `src/tools/` 自动发现、签名校验、Agent 绑定 |
| | `permission_svc.py` | 系统权限白名单：运行时拦截 |
| | `permission_guard.py` | 工具执行前的 `require_permission(kind)` + 启发式工具名匹配 |
| | `events_svc.py` | 审计事件持久化 + 周期 janitor（6h 一次，30 天/项目 10k 行保留） |
| | `log_svc.py` | 日志查询、按 source 分流、归档 |
| | `watchdog_svc.py` | 卡死探测 + orphan-running 项目启动时 reconcile |
| | `planner_cache_svc.py` | PM v3/v4 5-phase 内存缓存（in-memory，进程级，"save to persist" 语义） |
| | `planner_persist_svc.py` | PM v3/v4 草稿落地为真实项目（cache → DB + .mycrew/） |
| | `blueprint_writer.py` | 把 blueprint dict 写入 `<root>/.mycrew/`（独立模块供 persist_svc 复用） |
| **agents/sub_agents/** | `_planner_orchestrator.py` | PM v3/v4 5-phase 编排（完整度判定 → 主策划 → 系统策划 → 审核 → 项管 → 指挥员） |
| | `_planner_models.py` | Pydantic 渐进式增强模型：ConceptDoc → AtomicTask → ReviewedTask → PathedTask + Assignment(PerformerRef) |
| | `_planner_tools.py` | 5 个 phase-specific submit_xxx 工具（CrewAI BaseTool） |
| | `_planner_prompts.py` | 5 个 phase 的 role/goal/backstory 模板 |
| | `_list_performers_tool.py` | PM v4 Phase 5 `list_performers` 工具（返回 standalone agent + Crew 池） |
| | `task_guidance.py` | 单任务诊断聊天（任务卡片右上对话按钮 / Crew sub-card 对话），可 scope 到单个 Crew step |
| | `create_new.py` / `iterate_existing.py` | 创建模式 / 迭代模式入口（薄封装 `_planner_orchestrator.run_crew`） |
| **domain/** | `harness/` | 项目运行状态机（纯领域逻辑、零 IO） |
| | `qa/` | DAG 健壮性校验 + Task 输出 schema 校验调度 |
| | `experience/` | 经验库读写、tag 相关性匹配（CrewAI long-term memory 抽象） |
| | `events.py` | Domain Event 定义（dataclass） |
| **ports/** | `llm_port.py` `mcp_port.py` `repo_port.py` `interaction_port.py` `event_bus_port.py` | Protocol 接口；领域/服务通过这些类型依赖 |
| **infra/** | `llm/gateway.py` + provider adapter | LLM 实现（含 90s 硬超时） |
| | `mcp/stdio_client.py` `http_client.py` `pool.py` | MCP 连接实现 + 心跳 + 指数退避重连 |
| | `repo/sqlite_repo.py` | SQLite + WAL；连接时跑 `wal_checkpoint(TRUNCATE)` 防 WAL 累积 |
| | `repo/crud.py` | 通用 CRUD + **SQL fragment 守卫**（表名/列名/WHERE/ORDER BY 白名单 + 黑名单 +param-count 检查） |
| | `interaction/ws_interaction.py` | 通过 WS 收集用户回应（替代 input()） |
| | `event_bus/in_memory_bus.py` | 进程内 pub/sub |
| | `runtime.py` | 主事件循环引用（CrewAI worker thread 通过它 hop 回主 loop） |
| | `request_context.py` | request_id contextvar + structlog 处理器 |
| **bootstrap/** | `app.py` `main.py` `paths.py` | FastAPI 装配（含 CORS / audit / request_id 三层 middleware）、uvicorn 入口、路径常量 |
| | `seed_builtin_tools.py` | 79 个 builtin tool 行的幂等 seed |
| | `seed_plan_maker.py` | Plan Maker agent 行的幂等 seed（保留供 inception session 作 chat author tag） |
| | `seed_planner_agents.py` | 项目初始化助手 agent seed（pinned 到 deepseek-flash） |
| | `seed_crews.py` | PM v4 的 14 个 standalone-eligible agent + 8 个 Crew seed（**diff-then-update**：内容相同跳过 UPDATE） |
| | `wipe_v4.py` | 一次性 PM v4 reset（守 `_v4_reset_done.flag`；备份 DB → 删老项目 + 12 个废 agent） |

### 2.3 Tauri 壳层模块（Rust）

| 模块 | 职责 |
|---|---|
| `src-tauri/src/main.rs` | App 生命周期、Builder 装配、单实例锁、窗口创建、菜单/托盘 |
| `src-tauri/src/sidecar.rs` | sidecar 启动、端口探测/握手、健康检查、崩溃重启（指数退避） |
| `src-tauri/src/commands.rs` | `#[tauri::command]`：`pick_file` / `open_external` / `get_version` / `secret_set` / `secret_get` |
| `src-tauri/src/lifecycle.rs` | 窗口关闭协调 → 调后端 `/lifecycle/state` → 二次确认 → shutdown sequence |
| `src-tauri/tauri.conf.json` | 窗口尺寸/sidecar 路径/权限 allowlist |
| `src-tauri/Cargo.toml` | 依赖：tauri 2.x、single-instance、stronghold、updater、reqwest |

---

## 3. 通信契约

### 3.1 REST

- **基址**：`http://127.0.0.1:18321/api/v1/`（仅监听 loopback）
- **请求/响应 header**：每个响应带 `X-Request-ID`（12 位 hex）；客户端可通过同名请求头自带 id 用于跨调用追踪。
- **统一响应格式**：

```json
// 成功
{ "ok": true, "data": { ... } }

// 失败
{ "ok": false, "error": { "code": "string", "message": "string" } }
```

**关键端点一览**：

| 分组 | 端点 | 说明 |
|---|---|---|
| 立项对话 | `POST /inceptions` | 开启会话 |
| | `POST /inceptions/:id/messages` | 发消息（SSE 流式回包） |
| | `POST /inceptions/:id/index-path` | 索引本地文件目录 |
| | `POST /inceptions/:id/finalize` | 确认生成项目 |
| | `GET /inceptions` | 历史会话列表 |
| 项目 | `GET /projects?page=&size=4` | 分页列表 |
| | `POST /projects/:id/clone` | 复制项目 |
| | `DELETE /projects/:id` | 删除（含名称二次确认） |
| | `PUT /projects/:id/root-path` | 设置根目录 |
| | `POST /projects/:id/start\|pause\|resume` | 控制项目运行 |
| 任务 | `GET /tasks?project_id=` | 项目下任务列表 |
| | `PUT /tasks/:id` | 编辑详情（仅非运行态） |
| | `POST /tasks/:id/pause\|rerun\|intervene` | 任务控制 |
| | `GET /workflow/tasks/:id/io?direction=in\|out` | 查看任务输入/输出 |
| | `GET /workflow/tasks/:id/sub_io?step_index=N` | **PM v4**：查看 Crew 任务单步 IO |
| | `POST /workflow/tasks/:id/guidance` | 任务诊断聊天（可带 `step_index` scope 到 Crew 单步） |
| PM v3/v4 | `GET /pm/sessions/:session_id/state` | 5-phase 实时进度 + 草稿 |
| | `POST /pm/sessions/:session_id/save` | 草稿落盘成真实项目（可附 `override_blueprint`） |
| | `POST /pm/sessions/:session_id/restart` | 从断点重跑 |
| | `POST /pm/sessions/:session_id/cancel` | 取消当前 round |
| 鉴权 | `GET /auth/ws_token` | **新增**：返回 WS session token（localhost-only） |
| MCP | `GET /mcp/servers` | 服务器列表 |
| | `POST /mcp/servers` | 新增 |
| | `POST /mcp/servers/:id/restart` | 重启单个 |
| | `POST /mcp/refresh-all` | 强制全量重连 |
| LLM | `GET /llm/providers` | Provider 列表 |
| | `PUT /llm/providers/:id` | 更新配置 |
| | `GET /llm/quota` | Token 用量（30s TTL 缓存） |
| Agent/Crew/Tool | `GET\|POST\|PUT\|DELETE /agents\|/crews\|/tools` | 标准 CRUD |
| | `POST /tools/scan` | 扫描 src/tools 目录 |
| 权限 | `GET\|PUT /permissions` | 白名单矩阵 |
| 日志 | `GET /logs?source=&level=&since=` | 结构化日志查询 |
| 配置 | `GET\|PUT /config` | 应用配置 |

### 3.2 WebSocket

- **端点**：`ws://127.0.0.1:18321/api/v1/ws?token=<session-token>`，单连接、双向。
- **鉴权（新增 2026-05-16）**：每次后端启动生成一个随机 token，写到 `data/runtime/session.token` 并通过 stdout 打印 `MYCREW_WS_TOKEN=…`。前端通过 `GET /api/v1/auth/ws_token` 拿 token 后挂在 `?token=` 上。token 不匹配 → handshake 关闭码 `4401`，前端清缓存自动重连刷新 token。
- **消息格式**：`{ "type": "string", "ts": "ISO8601", "payload": {} }`

**事件类型**：

| 分组 | 事件 | 说明 |
|---|---|---|
| `inception.*` | `inception.delta` | 流式 token |
| | `inception.message` | 单轮完整助手消息 |
| | `inception.tasks_drafted` | AI 拆解结果（v2 兼容路径） |
| | `inception.workflow_created` | 草稿保存成项目后广播 |
| | `inception.sub_agent_io` | sub-agent 的输入/输出追踪 |
| `pm.log` | `pm.log` | **PM v3/v4**：5-phase 实时进度日志 |
| `project.*` | `project.started` / `project.paused` / `project.resumed` / `project.completed` / `project.aborted` / `project.progress` | 项目生命周期 |
| `task.*` | `task.started` / `task.completed` / `task.failed` / `task.paused` / `task.blocked` | 任务生命周期 |
| | `task.validation.failed` | schema 校验失败（含错误详情） |
| | `task.sub_step` | **PM v4**：Crew 子步骤 `started`/`completed`/`failed`，前端 `CanvasCrewNode` sub-card 实时高亮 |
| `mcp.*` | `mcp.status_changed` / `mcp.tool_call` | MCP 连接状态 |
| `tool.invoked` | `tool.invoked` | 每次工具调用的 audit 事件（`started`/`completed`/`denied`/`failed`） |
| `agent.output` | `agent.output` | CrewAI step callback 推送的中间输出（含 Crew 子步骤） |
| `prompt.*` | `prompt.request` / `prompt.response` | 人工介入双向交互 |
| `lifecycle.*` | `lifecycle.recovery_prompt` | 启动时恢复提示 |
| `ws.*` | `ws.connected` / `ws.disconnected` | 前端本地合成（非后端推送），用于连接状态指示 |

### 3.3 InteractionPort 协议

替代 `input()` 的人工介入抽象。详见 [ADR-008](ADR/008-interaction-port.md)。

```python
class InteractionPort(Protocol):
    async def prompt_choice(self, ctx: PromptCtx, options: list[Choice]) -> str: ...
    async def prompt_text(self, ctx: PromptCtx, hint: str = "") -> str: ...
    async def prompt_confirm(self, ctx: PromptCtx) -> bool: ...
```

**WS 实现流程**：服务端发出 `prompt.request`（带 `request_id`）→ 挂起 Future → 前端用户操作 → 回送 `prompt.response` → 服务端 resolve Future。超时/断连有兜底处理。

---

## 4. 数据架构

### 4.1 SQLite 数据库

主存储：`data/db/mycrew.db`（aiosqlite + Repo 模式，不引入 ORM）。迁移工具：Alembic（`op.execute` 原生 SQL）。

| 表 | 用途 | 关键字段 |
|---|---|---|
| `projects` | 项目元数据 | id, name, root_path, state, is_running(bool), progress_pct, execution_kind(sequential\|crew\|flow), parent_project_id, iteration_index, template_id, favorited_at |
| `inception_sessions` | 立项对话 | id, llm_id, thinking_mode, system_prompt, indexed_paths(JSON), template_id, mode(create\|iterate), last_activity_at, title |
| `inception_messages` | 立项对话消息 | id, session_id, role, content, ts |
| `tasks` | 项目下任务 | id, project_id, title, detail, agent_id, kind(regular\|final_qa\|setup), output_schema(JSON Schema), status, deps(JSON), io_in_ref, io_out_ref, position_x/y, last_activity_at, validation_errors, last_error, last_error_kind, **performer_kind(agent\|crew)**, **performer_id** (PM v4) |
| `agents` | Agent 模板 | id, role, goal, backstory, reasoning, max_retry, memory_enabled, thinking_mode, tool_ids(JSON), llm_id, is_auto_generated |
| `crews` | Crew 编排 | id, name, process(sequential\|hierarchical), agent_ids(JSON), is_auto_generated, **applicable_scenarios** (PM v4 Phase 5 选 Crew 时读), **agent_sequence** (JSON head→executors→QA 链路) |
| `tools` | Tool 注册 | id, name, script_path, source(builtin\|user), checksum, params_schema(JSON) |
| `events` | 审计/事件日志 | id, ts, event_type, actor, project_id, task_id, session_id, payload(JSON)（6h janitor 30 天 / 项目 10k 行保留） |
| `mcp_servers` | MCP 配置 | id, name, transport(stdio\|http), command/args/url, env_ref(JSON), discovered_tools(JSON) |
| `llm_providers` | LLM 配置 | id, name, type(openai/anthropic/qwen/deepseek/gemini/ollama/custom), api_key_ref, base_url |
| `llm_models` | 模型清单（provider 一对多） | id, provider_id, model_name, label, max_tokens, supports_thinking |
| `app_settings` | 应用设置 key-value | default_inception_model, default_agent_model, task_concurrency_limit, 主题等 |
| `permissions` | 系统权限白名单 | id, kind, pattern, allowed |
| `chat_sessions` / `chat_messages` | Agent 对话历史（失败介入） | — |
| `logs` | 结构化日志 | 含 source 字段（多终端 tab） |
| `prompt_audit` | 人工介入审计 | request_id, ctx, user_response, latency_ms |

**Task 状态机**：`pending → running → done | failed | validation_failed | aborted`，另有 `paused`（暂停）和 `blocked`（上游失败阻塞）。

**项目状态机**：`READY → RUNNING ⇄ PAUSED → COMPLETED | COMPLETED_WITH_WARNINGS | COMPLETED_WITH_ISSUES | ABORTED`

### 4.2 文件存储布局

```
data/
├─ config/app.yaml             # 用户配置（theme, language, default model 等）
├─ db/mycrew.db                 # SQLite 主库（WAL 模式）
├─ db/mycrew.db.pre-v4.<ts>     # wipe_v4 留下的一次性备份（手动清理）
├─ logs/{YYYYMMDD}.jsonl        # 滚动日志（如启用）
├─ cache/mcp_health/            # MCP 心跳缓存
├─ secrets/                     # （未来加密 keystore 占位；当前 LLM key 仍存 DB）
└─ runtime/
   ├─ last_state.json           # 异常退出前的运行态快照
   ├─ session.token             # **WS session token**（每次启动重写）
   └─ _v4_reset_done.flag       # wipe_v4 已运行标志（删除该文件可触发再 reset）

output/
└─ {project_id}/                # 项目级目录
   └─ {task_id}/
      ├─ in.json / in.md        # 任务输入（结构化 + 人类可读）
      ├─ out.json / out.md      # 任务输出
      └─ sub/                   # **PM v4** Crew 任务的 sub-step IO
         ├─ 0_head_in.json
         ├─ 0_head_out.json
         ├─ 0_head_out.md
         ├─ 1_executor_in.json
         ├─ 1_executor_out.json / out.md
         └─ N_qa_in.json / out.json / out.md
```

### 4.3 凭证管理

遵循**单一信源原则**。详见 [ADR-001](ADR/001-credentials.md)。

| 角色 | 职责 |
|---|---|
| **Tauri 主进程（Rust）** | 凭证唯一持有者。用 `tauri-plugin-stronghold` 主存 + `tauri-plugin-keyring` 可选托管主密码到 OS Keychain。失败回退 DPAPI 加密。 |
| **Python sidecar** | 不保存凭证。每次需要时通过 `GET /internal/secrets/:key`（loopback + 一次性 token）从主进程拉取，用完即丢。 |
| **前端** | 永远只见掩码。写入新值通过 `invoke('secret_set', ...)` 直接交 Rust 主进程，不经 Python。 |

### 4.4 写入策略

| 数据类型 | 策略 |
|---|---|
| 关键状态（task.status / project.state） | 同步落库，先 commit 再发事件 |
| 高频更新（task.progress %） | 节流写库（每 2s 或 5% 变化），内存最新值通过 WS 推送 |
| 文件型大对象（IO） | 不入 DB，存 `output/`，DB 只存路径引用 |

---

## 5. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 桌面壳 | **Tauri 2.x (Rust)** | 包体积小（~10MB）、内存低、安全模型严格；已具备 Electron 等价能力。详见 [ADR-001](ADR/001-credentials.md) |
| 前端框架 | **React 19 + Vite 6 + TypeScript 5** | HMR 快、社区生态丰富 |
| UI 库 | **Tailwind 4 + Shadcn/ui** | 按需 copy-in 组件，可控性强 |
| 国际化 | **i18next** | UI 主语言中文，预留 i18n 接口 |
| 状态管理 | **Zustand + React Query** | Zustand 处理 UI 状态，RQ 处理服务端状态缓存 |
| 后端框架 | **FastAPI + Uvicorn (single worker)** | 异步原生、Pydantic v2 校验、OpenAPI 自动生成 |
| Crew 引擎 | **CrewAI 最新稳定版** | 项目核心定位 |
| MCP 客户端 | **官方 `mcp` Python SDK** | stdio + http 全覆盖 |
| 持久化 | **SQLite + aiosqlite** | 单机本地、零运维 |
| 数据库迁移 | **Alembic**（原生 SQL，不用 ORM 模型） | 版本化迁移、升降级可控 |
| 加密 | **tauri-plugin-stronghold + DPAPI 回退** | 跨平台原生凭证存储 |
| 日志 | **structlog（Python）+ tracing（Rust）** | JSON 行格式便于聚合 |
| 测试 | **pytest + Vitest + Playwright + cargo test** | 后端/前端/E2E/壳层全覆盖 |
| 打包 | **PyInstaller + Tauri bundler (NSIS/MSI)** | Windows 一站式分发 |

> 不引入 K8s/Docker/MySQL/Kafka——单机桌面应用，"高可用"的含义是 **sidecar 健康检查 + 崩溃重启 + 状态可恢复**。

---

## 6. 项目目录结构

```
MyCrew_v3/
├─ src-tauri/                   # Tauri Rust 壳层
│  ├─ src/
│  │  ├─ main.rs                #   App 装配 + 单实例
│  │  ├─ sidecar.rs             #   Python sidecar 生命周期
│  │  ├─ commands.rs            #   #[tauri::command] 集合（仅本地能力）
│  │  └─ lifecycle.rs           #   优雅关闭协调
│  ├─ tauri.conf.json           #   窗口/sidecar/权限 allowlist
│  ├─ Cargo.toml
│  └─ icons/
├─ frontend/                    # React 前端（Tauri 内嵌 webview 加载）
│  ├─ src/
│  │  ├─ pages/                 #   4 页面组件
│  │  ├─ components/            #   通用 UI 组件
│  │  ├─ queries/               #   React Query hooks (use*Query)
│  │  ├─ stores/                #   Zustand stores (use*Store)
│  │  ├─ net/                   #   api.ts + ws.ts
│  │  ├─ hooks/                 #   useEvent 等自定义 hooks
│  │  ├─ types/                 #   TypeScript 类型定义
│  │  └─ styles/                #   Tailwind 配置与全局样式
│  ├─ vite.config.ts
│  └─ package.json
├─ backend/                     # Python sidecar
│  ├─ api/                      #   REST 路由 + WS Hub
│  ├─ services/                 #   业务逻辑层
│  ├─ domain/                   #   领域层（状态机、QA、经验）
│  ├─ ports/                    #   Protocol 接口
│  ├─ infra/                    #   基础设施实现
│  ├─ bootstrap/                #   DI 容器、路径、FastAPI 装配、入口
│  ├─ migrations/               #   Alembic 迁移脚本
│  ├─ tests/
│  ├─ alembic.ini
│  └─ pyproject.toml
├─ src/                         # 用户可扩展源代码区
│  ├─ tools/                    #   用户自定义 Tool 脚本（BaseTool 子类）
│  ├─ agents/                   #   （可选）预置 Agent 模板 YAML
│  └─ crews/                    #   （可选）预置 Crew 编排 YAML
├─ data/                        # 运行时数据（gitignored）
│  ├─ config/app.yaml
│  ├─ db/mycrew.db
│  ├─ logs/
│  ├─ cache/mcp_health/
│  ├─ secrets/keystore.json
│  └─ runtime/last_state.json
├─ output/                      # 项目产物（gitignored）
├─ docs/                        # 文档按四档分类（详见 docs/README.md）
│  ├─ spec/                     #   稳态参考（ARCHITECTURE / API / STORAGE-MAP / DESIGN-SYSTEM / BUILD / USER_GUIDE）
│  ├─ iterations/               #   按日期归档的迭代日志（含本轮 audit + followup）
│  ├─ roadmap/                  #   未来规划 + 设计草案（含 MCP / OpenClaw 集成预案 + next-audit-prep）
│  ├─ ADR/                      #   8 条架构决策记录
│  ├─ archive/                  #   被替代的历史文档
│  ├─ dev-notes/                #   开发笔记 / 调试踩坑
│  └─ figma/                    #   设计稿引用
├─ scripts/                     # 启停 / 打包 / 数据库迁移
├─ .gitignore
├─ .env.example
├─ README.md
├─ Description.md
├─ meta.json
└─ assets/
```

---

## 7. 关键设计决策

以下为核心架构决策摘要，完整论证与替代方案对比记录在各 ADR 文档中。

### 7.1 桌面壳层选型：Tauri 2.x

v2 弃用 Tauri 的根因是紧耦合架构与 sidecar 集成经验不足，非 Tauri 本身缺陷。Tauri 2.x 已具备 Electron 等价能力（sidecar/单实例锁/凭证存储/自动更新），包体积约为 Electron 的 1/8。前端代码与 Tauri 解耦，切换壳层成本集中在 `src-tauri/` 薄层。

> 详见 [ADR-001](ADR/001-credentials.md)

### 7.2 项目指令结构化入库

项目"指令"纯结构化存入 DB（`tasks` 表 + JSON Schema），不再像 v2 那样生成 YAML 文件。

> 详见 [ADR-002](ADR/002-structured-instructions.md)

### 7.3 单项目运行限制

当前版本同时只允许一个项目处于 running 状态，简化 `workflow_svc` 调度器复杂度。DB schema 用 `is_running` bool 字段实现，不做数据库硬约束，便于未来放开并发。

> 详见 [ADR-003](ADR/003-single-project-running.md)

### 7.4 LLM 配置模型

一条 LLM 记录 = 1 个 provider + key，下挂一对多 model（`llm_providers` / `llm_models` 嵌套表）。双默认设置：立项默认 + Agent 默认。

> 详见 [ADR-004](ADR/004-llm-provider-model.md)

### 7.5 Tool 扩展协议

用户 Tool 必须是 CrewAI `BaseTool` 子类，放在 `src/tools/` 下。启动时自动扫描 + 手动扫描。首次发现弹信任确认；checksum 变更再次确认。

> 详见 [ADR-005](ADR/005-tool-protocol.md)

### 7.6 MCP 工具包装层

不依赖 CrewAI 的 dynamic MCP integration。每个常用 MCP 工具写一个手工 `BaseTool` 子类（放在 `src/tools/builtin/mcp_<server>/`），`args_schema` 严格按 MCP 官方文档定义。未被手写包装的 MCP 工具对 Agent 不可见。

```python
# src/tools/builtin/mcp_blender/execute_code.py 示例
class ExecuteBlenderCodeArgs(BaseModel):
    code: str = Field(..., description="Python code to execute in Blender")

class ExecuteBlenderCode(BaseTool):
    name: str = "execute_blender_code"
    description: str = "Execute arbitrary Python in Blender's runtime"
    args_schema: type[BaseModel] = ExecuteBlenderCodeArgs

    def _run(self, code: str) -> str:
        return mcp_pool.call("blender", "execute_blender_code", {"code": code})
```

### 7.7 Task 输出契约

每个 Task 必须有 `output_schema`（JSON Schema）。运行期流程：

1. Agent 执行完产出 free text
2. 同一 LLM 做 structured output 提取（保持语义同源）
3. Pydantic 校验通过 → `done`；失败 → 自动重试（计入 `max_retry`）；预算用完 → `validation_failed` 进入人工介入
4. 下游 Task 的 input 按 `{upstream_task_id: <output_schema 实例>}` 字典组装

schema 为 `{}` 时退化为 free text 模式（v2 行为），不做校验。

### 7.8 自动生成资源管理

立项 LLM 可通过内置 Tool（`agent_factory` / `crew_factory`）动态创建 Agent/Crew，入全局库并带 `is_auto_generated=true` 标记。团队页以特殊徽章展示。

> 详见 [ADR-006](ADR/006-auto-generated-resources.md)

### 7.9 项目根目录定位

项目根目录（`root_path`）仅作为 Agent 默认产出路径，不限制读写范围。个人单机定位下权限为 9 个全局布尔开关，默认全开。

> 详见 [ADR-007](ADR/007-project-root-path.md)

---

## 8. 生命周期管理

### 8.1 优雅关闭

用户关窗 / 系统关机时，Tauri 主进程主导 shutdown sequence：

1. 检查后端：`GET /lifecycle/state` → 获取运行中项目数
2. 有运行中项目 → 弹二次确认
3. 确认后按序执行：暂停所有项目（30s 超时）→ 持久化运行态到 `last_state.json` → 关闭 MCP 子进程（5s 等待 → 强杀）→ flush 日志与 DB → 后端进程退出（10s 超时） → 窗口关闭

### 8.2 启动加载

冷启动流程：

1. Tauri 主进程 → 单实例锁 → spawn Python sidecar → 端口握手
2. 后端 lifespan 按序执行：
   - 加载 `app.yaml` 配置
   - 初始化 SQLite + Alembic 迁移
   - 加载所有静态配置到内存
   - 扫描 `src/tools/` 注册用户插件
   - 检查 `last_state.json` → 有未完成项目则通过 WS 提示恢复
   - 按上次活动列表自动启动 MCP 池
3. 前端连接 → 拉取数据 → 渲染主页

### 8.3 崩溃自愈

Tauri 主进程监听 sidecar `CommandEvent::Terminated`，退出码非 0 时指数退避重启（最多 3 次），失败后弹错误页 + "导出诊断包"。

---

## 9. 数据流关键路径

### 建项目

```
用户对话 → inception_svc 调 LLM
  → 流式 inception.delta（WS）
  → AI 输出任务草案 inception.tasks_drafted（WS）
  → 用户编辑蓝图
  → POST /inceptions/:id/finalize
  → project_svc 生成项目卡
```

### 跑任务

```
用户点开始 → workflow_svc 启 Harness
  → 状态机驱动 DAG 遍历
  → 每步发 task.*/project.progress（WS）
  → Agent 输出 → structured extraction → schema 校验
  → 失败时发 prompt.request（WS）等用户介入
  → 全部完成 → final_qa → verdict → 项目最终状态
```

### 暂停/恢复

```
POST /projects/:id/pause
  → workflow_svc 标记 paused
  → 当前任务跑完后停止调度后续
  → 恢复：POST /projects/:id/resume → 从暂停点继续
```

---

## 10. 高可用与可观测性

| 能力 | 实现 |
|---|---|
| 崩溃自愈 | sidecar 退出码监听 + 指数退避重启（最多 3 次） |
| 状态可恢复 | 每次状态转移落库 + `last_state.json` 快照 + 启动恢复提示 |
| 资源监控 | 主进程采集 sidecar CPU/内存 → WS 推到状态条 |
| 诊断包导出 | 一键打包 logs + 脱敏配置 + 系统信息 → `.zip` |
| MCP 故障隔离 | 单个 MCP 崩溃不影响其他；独立子进程 + 心跳超时强杀 |
| 结构化日志 | 每条带 ts/level/source/project_id/task_id/event/message，JSON 行格式 |
| 追踪 ID | Tauri Command → REST → WS 事件全程贯穿同一 request_id |

---

## 11. PM v4 — Crew-Native 执行架构（2026-05-16 落地）

> **完整设计**：`docs/iterations/2026-05-16/pm-v4-plan.md` + 13 轮 grill 决策。
> **落地报告**：`docs/iterations/2026-05-16/audit-followup-2026-05-16.md`。
> **本节是稳态视角**：v4 跑通后系统长什么样。

### 11.1 与 v3 的本质差异

v3 假设「一个 task = 一个 agent」。v4 引入「Crew 任务」：一个 task 可以绑到一个 **Crew**，由多个 sub-agent 按 head → executors → QA 链路串行执行。

| 维度 | v3 | v4 |
|---|---|---|
| 任务执行单位 | 单个 agent | agent（不变）**或** Crew |
| `tasks.performer_kind` | NULL（旧字段 `agent_id`） | `agent` / `crew` |
| `tasks.performer_id` | NULL | agent_id 或 crew_id |
| Crew 内部协作 | — | `crews.agent_sequence` JSON 定义 head/executors/QA + 每步 `step_instructions` + `progress_template` |
| 输出捕获 | 单个 emit_output 落 `out.json` | 每个 sub-step 落 `sub/<i>_<role>_*.json`；QA step 同时写到 task 级 `out.json` |
| WS 事件 | `task.*` | `task.*` + 新增 `task.sub_step` |

### 11.2 Phase 5 — Performer 池

PM 工作流变成 5 phase：完整度判定 → 主策划 (ConceptDoc) → 系统策划 (AtomicTask) → 审核策划 (ReviewedTask) → 项管 (PathSpec/PathedTask) → **指挥员（Phase 5：从预设池选 performer）**。

Phase 5 LLM 必须先调 `list_performers(kind="all")` 工具拿到当前可用 performer 真相，再调 `submit_assignments`。`submit_assignments` schema 不含 `new_agent` 字段，编造的 id 被 Pydantic + `_validate_assignments` 二次校验拦截。

**Performer 池**：8 个预设 Crew（Art / 3D Asset / Animation / VFX / System Impl / UI Impl / Audio / Scene Assembly）+ 5 个 standalone agent（Narrative Designer / Level Designer / System Designer / Art Director / 项目初始化助手）。详见 `backend/bootstrap/seed_crews.py`。

### 11.3 Crew 执行路径

```
workflow_svc._run_agent
  ├─ task.performer_kind == "crew" → _run_crew
  │     for step in agent_sequence:
  │       ├─ 检查 paused flag（Q7 软暂停，step 边界检查）
  │       ├─ run_crew_step_with_crewai(单 agent + 单 task 的 CrewAI kickoff)
  │       ├─ pop emit_output capture (绑定 task_id#step{i})
  │       ├─ 写 sub/<i>_<role>_{in,out}.{json,md}
  │       ├─ broadcast task.sub_step started/completed/failed
  │       └─ 把当前 step 的捕获 payload 注入下一步的 description
  │     # QA step 的 emit_output 直接写到 task_id 槽位 → 走原有 post-process
  └─ task.performer_kind != "crew" → 原 _run_agent_direct / run_task_with_crewai
```

### 11.4 任务卡片画布（前端）

- `CanvasTaskNode` —— 普通 agent 任务（240px）
- `CanvasCrewNode` —— Crew 任务（折叠时是 240px 普通卡片 + ⊕ 按钮；展开后是 header + 一排 `SubAgentCard`）
- 展开时通过 `onWidthChange` 上报 delta，`CanvasBlueprint.offsetFor` 给下游节点加横向偏移（"自动平移下游"），收起复位
- `SubAgentCard` 按 Q11 gating：Head 保留完整动作（edit/pause/retry/chat/IO），Executor + QA 只读（chat + IO）
- 子卡片对话 / IO 查看通过 `step_index` 入参 scope 到单个 step（端点：`GET /workflow/tasks/{id}/sub_io` + `POST /workflow/tasks/{id}/guidance`）

---

## 12. 安全 / 鲁棒性加固模块（2026-05-16 Phase 1/2 落地）

| 模块 | 位置 | 作用 |
|---|---|---|
| WS session token | `api/ws.py` + `api/routes_auth.py` + `bootstrap/app.py` lifespan | 每次启动生成随机 token；`?token=` 校验失败关闭码 4401；前端通过 `GET /auth/ws_token` 获取（localhost-only） |
| WorkflowService per-project Lock | `services/workflow_svc.py` `_project_locks` | start/pause/resume/abort/retry 同 project 串行；不同 project 并行 |
| 补偿事务 | `services/project_svc.py` `create_project_with_tasks` | 两遍插入中异常 → `delete_project` 回滚，无半成品残留 |
| SQL fragment 守卫 | `infra/repo/crud.py` `_validate_table` / `_validate_where` / `_validate_order_by` + `SqlFragmentError` | 表/列名严格识别符；WHERE/ORDER BY 拒绝 `;` `--` `/*` `\x00`；`?` 数 = params 长度 |
| request_id middleware | `bootstrap/app.py` `_request_id_middleware` | 每个 HTTP 请求 12 hex 字符 ID；structlog `merge_contextvars` 自动传播；响应头 `X-Request-ID` |
| 异常分类 | `services/workflow_svc.py` `_classify_task_error` | 8 种 kind（quota/auth/mcp/network/validation/stalled/tool/unknown），前端用作错误 tooltip headline |
| `_output_capture` TTL | `src/tools/builtin/local/_output_capture.py` `_evict_expired` | 任务 1h / planner 4h 摊销清理 |
| WAL TRUNCATE | `infra/repo/sqlite_repo.py` `get_db` | 连接时强制 `wal_checkpoint(TRUNCATE)` 防 WAL 累积 |
| Diff-then-update seed | `bootstrap/seed_crews.py` `_ensure_agent` | 内容相同跳过 UPDATE，避免启动时 14 行无意义写锁 |
| watchdog orphan reconcile | `services/watchdog_svc.py` | 启动时把残留 `state=running` 项目按 task 终态推断到 STALLED / COMPLETED_WITH_ISSUES / PAUSED |
| LLM 硬超时 | `infra/llm/gateway.py` `LLM_CALL_TIMEOUT_SECONDS=90` | 网络抖动场景的兜底，避免任务无限挂起 |

---

## 附录 A：ADR 索引

| 编号 | 决策 | 文件 |
|---|---|---|
| ADR-001 | 桌面壳层选 Tauri 2.x 而非 Electron | `docs/ADR/001-credentials.md` |
| ADR-002 | 项目指令纯结构化入 DB，不生成 YAML | `docs/ADR/002-structured-instructions.md` |
| ADR-003 | 同时只能运行一个项目 | `docs/ADR/003-single-project-running.md` |
| ADR-004 | LLM 记录 = 1 provider+key 配多 model | `docs/ADR/004-llm-provider-model.md` |
| ADR-005 | 用户 Tool 必须是 CrewAI BaseTool 子类 | `docs/ADR/005-tool-protocol.md` |
| ADR-006 | 自动生成 Agent/Crew 入全局库带标记 | `docs/ADR/006-auto-generated-resources.md` |
| ADR-007 | 项目根目录仅作默认产出路径，不限制读写 | `docs/ADR/007-project-root-path.md` |
| ADR-008 | InteractionPort 通过 WS prompt 替代 input() | `docs/ADR/008-interaction-port.md` |
