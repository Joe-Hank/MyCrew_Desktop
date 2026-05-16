# MyCrew v3 — 架构文档

> 本文档是 MyCrew v3 的架构参考手册。设计决策的完整背景与权衡记录在 `docs/ADR/` 目录下。

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
| **services/** | `project_svc.py` | 项目 CRUD、复制、删除、卡片分页 |
| | `inception_svc.py` | 建项目对话：管理立项会话、调用 LLM 拆解任务、文件索引、执行结构选择、动态资源生成 |
| | `workflow_svc.py` | 启动/暂停/恢复 Harness；暂停语义：当前任务跑完后截断后续链 |
| | `mcp_svc.py` | MCP 服务器池：启动、心跳、工具列表缓存、全量重连 |
| | `llm_svc.py` | LLM 配置、Token 用量轮询（百分比/M 数/可用性三态） |
| | `agent_svc.py` | Agent 模板 CRUD：角色/目标/能力/工具绑定 |
| | `crew_svc.py` | Crew CRUD：队名/过程/角色组合 |
| | `tool_svc.py` | Tool CRUD：扫描 `src/tools/` 自动发现、签名校验、Agent 绑定 |
| | `permission_svc.py` | 系统权限白名单：运行时拦截 |
| | `log_svc.py` | 日志查询、按 source 分流、归档 |
| **domain/** | `harness/` | 项目运行状态机（纯领域逻辑、零 IO） |
| | `qa/` | DAG 健壮性校验 + Task 输出 schema 校验调度 |
| | `experience/` | 经验库读写、tag 相关性匹配（CrewAI long-term memory 抽象） |
| | `events.py` | Domain Event 定义（dataclass） |
| **ports/** | `llm_port.py` `mcp_port.py` `repo_port.py` `interaction_port.py` `event_bus_port.py` | Protocol 接口；领域/服务通过这些类型依赖 |
| **infra/** | `llm/openai_adapter.py` `anthropic_adapter.py` `qwen_adapter.py` | LLM 实现 |
| | `mcp/stdio_client.py` `http_client.py` `pool.py` | MCP 连接实现 |
| | `repo/sqlite_repo.py` `file_repo.py` | 持久化实现 |
| | `interaction/ws_interaction.py` | 通过 WS 收集用户回应（替代 input()） |
| | `event_bus/inproc_bus.py` | 进程内 pub/sub |
| **bootstrap/** | `container.py` `paths.py` `app.py` `main.py` | 依赖注入容器、路径常量、FastAPI 装配、uvicorn 入口 |

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
| | `GET /tasks/:id/io?direction=in\|out` | 查看输入/输出 |
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

- **端点**：`ws://127.0.0.1:18321/ws`，单连接、双向。
- **消息格式**：`{ "type": "string", "ts": "ISO8601", "payload": {} }`

**事件类型**：

| 分组 | 事件 | 说明 |
|---|---|---|
| `inception.*` | `inception.delta` | 流式 token |
| | `inception.tasks_drafted` | AI 拆解结果 |
| `project.*` | `project.state_changed` | 项目状态变化 |
| | `project.progress` | 进度更新 |
| `task.*` | `task.started` / `task.progress` / `task.completed` / `task.failed` / `task.paused` | 任务生命周期 |
| | `task.validation_failed` | schema 校验失败（含错误详情） |
| `mcp.*` | `mcp.connected` / `mcp.disconnected` / `mcp.tool_call` | MCP 连接状态 |
| `llm.*` | `llm.quota_changed` | Token 用量变化 |
| `tool.*` | `tool.scanned` | src/tools 目录变化 |
| `prompt.*` | `prompt.request` / `prompt.response` | 人工介入双向交互 |
| `log.*` | `log.append` | 实时日志推送（带 source 区分终端 tab） |
| `lifecycle.*` | `lifecycle.recovery_prompt` | 启动时恢复提示 |

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
| `projects` | 项目元数据 | id, name, root_path, state, is_running(bool), progress_pct, execution_kind(sequential\|crew\|flow) |
| `inception_sessions` | 立项对话 | id, llm_id, thinking_mode, system_prompt, indexed_paths(JSON) |
| `inception_messages` | 立项对话消息 | id, session_id, role, content, ts |
| `tasks` | 项目下任务 | id, project_id, title, detail, agent_id, kind(regular\|final_qa), output_schema(JSON Schema), status, deps(JSON), io_in_ref, io_out_ref |
| `agents` | Agent 模板 | id, role, goal, backstory, reasoning, max_retry, memory_enabled, thinking_mode, tool_ids(JSON), llm_id, is_auto_generated |
| `crews` | Crew 编排 | id, name, process(sequential\|hierarchical), agent_ids(JSON), is_auto_generated |
| `tools` | Tool 注册 | id, name, script_path, source(builtin\|user), checksum, params_schema(JSON) |
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
├─ config/app.yaml            # 用户配置（含加密 LLM key 引用）
├─ db/mycrew.db                # SQLite 主库
├─ logs/{YYYYMMDD}.jsonl       # 滚动日志
├─ cache/mcp_health/           # MCP 心跳缓存
├─ secrets/keystore.json       # OS keychain 失败时的 DPAPI 加密回退
└─ runtime/last_state.json     # 异常退出前的运行态快照

output/
└─ {YYYYMMDD_HHmm}_{Project}/  # CrewAI 运行产物
   └─ {task_id}/
      ├─ in.json / out.json    # 结构化输入/输出
      └─ in.md / out.md        # 原始过程记录
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
├─ docs/
│  ├─ ARCHITECTURE.md           # 本文档
│  ├─ API.md                    # OpenAPI 导出 + WS 事件清单
│  └─ ADR/                      # 架构决策记录
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
