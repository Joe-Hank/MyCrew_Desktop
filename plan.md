# MyCrew v3 — 架构与实施路线图

## Context

v2 版本（Tauri + React + FastAPI）已实现过完整桌面应用，但因 **整体用户体验不佳、核心功能不稳定** 被弃用。v3 将在空目录 `f:\ClaudeData\MyCrew_v3` 从零重构。

**产品定位**：Crewai + MCP 的本地服务窗口（PC 桌面应用），单机运行、无云部署需求。

**核心能力**：
1. 维护并实时监控多个 MCP 服务器的连接状态
2. 接入多家 LLM API（Claude / OpenAI / Qwen 等）
3. 通过 CrewAI 编排多 Agent 协作工作流
4. 项目进度自由管理（DAG、暂停、断点续跑、人工介入）
5. **对话驱动的项目立项**：用户用自然语言描述想法 → 拆解 LLM 输出可编辑任务 → 用户编辑确认 → 生成项目卡
6. **插件化扩展**：用户在 `src/tools/` 放置脚本即可作为新 Tool 被 Agent 调用；LLM/MCP 配置同样为"前端表单 + 后端脚本"结构

**项目执行结构（LLM 自主决定）**：
立项 LLM 在生成任务草案时，根据任务数量与依赖复杂度选择三种执行结构之一。**阈值不写死**，仅作为系统提示词中的参考给 LLM：
- 1~2 个任务 → 顺序调用 Agent，不建 Crew
- 3~5 个任务 → 单个 CrewAI Crew（sequential / hierarchical）
- 6+ 任务或复杂依赖（分支/汇合/循环） → CrewAI Flow，多子 Crew 编排
- LLM 可根据任务性质打破阈值（如 8 个纯顺序任务也可用 Crew）

**任务的 DAG 颗粒度**：DAG 中每个节点 = 一次原子级 Agent 调用（对应 CrewAI Task）。Crew 与 Flow 是后端编排方式，前端 DAG **不嵌套展开**，全部底层 Task 平铺为节点（依赖关系用线条表达）。

**Task 是唯一抽象**：无论 Task 处于 Crew 内、子 Crew 内、还是 Flow 编排节点上，**所有 Task 一致受 `output_schema` 约束**，跨任何边界传递都按结构化对象走。Crew / Flow 只是后端 `workflow_svc` 的调度层选择（影响多 Agent 协作模式与并发分组），**不改变契约语义**——这保证了 §11.7 的契约模型在简单和复杂项目中行为一致。

**资源缺失时自动生成**：当立项需要某个 Agent/Crew 但库中没有，立项 LLM 通过专用 Tool 创建。

**立项 LLM 的 Tool 集**（内置 BaseTool 子类，仅 inception_svc 注入，不会出现在团队页 Tools tab）：
- `agent_factory(role, goal, backstory, tool_ids?, mcp_server_ids?, llm_id?)` → 创建并入库（`is_auto_generated=true`），返回 agent_id
- `crew_factory(name, process, agent_ids)` → 创建并入库，返回 crew_id
- `list_agents()` / `list_crews()` / `list_tools()` / `list_mcp_servers()` → 查现有资源，避免重复生成
- `file_indexer(path, depth=3)` → 返回目录树 + 文件大小（不读内容，给 LLM 决定是否要读）
- `file_read(path, max_bytes=200_000)` → 受系统权限"文件读取"开关控制；超量截断
- **任务蓝图输出**：不用 tool，**LLM 在对话末尾按系统提示词输出 \`\`\`json\`\`\` 代码块**包含 `{ execution_kind, tasks: [{ title, detail, agent_id, deps: [...], output_schema: <JSON Schema>, kind?: "regular" | "final_qa" }] }`；后端解析失败时回退为"让用户手填"模式（见 §17 风险表）。每个 task 的 `output_schema` 必填（设为 `{}` 表示退化为 free text，不做契约校验）。
- **强制添加 final_qa task**：立项 LLM 在系统提示词中被要求**始终在 DAG 末端添加一个 `kind: "final_qa"` 的 Task**，依赖所有叶子节点（无下游的 task）。该 task 绑定一个内置 QA Agent（角色 = "项目总质检员"，goal = "审视整个项目交付物的目标达成度、跨 task 一致性、可能的遗漏"，输出 schema = `{ verdict: "pass|warn|fail", overall_score: number, issues: [{ severity, task_ref, description, suggestion }], summary: str }`）。如果立项 LLM 漏掉，后端在 finalize 校验阶段自动补一个。
- **final_qa 与 task QA 的分工**：每个 task 的 `output_schema` 校验解决"格式契约"问题；final_qa 解决"语义完整性 / 目标达成度"问题。两者互补，不重复。
- **verdict 与项目状态映射**：
  - verdict=`pass` → 项目 `state=completed`、卡片绿点。
  - verdict=`warn` → 项目 `state=completed_with_warnings`、卡片黄点；issues 列表可点入查看。
  - verdict=`fail` → 项目 `state=completed_with_issues`、卡片红点；issues 列表可点入查看；用户可一键"基于 issues 触发对应 task rerun"或"接受当前成果"。
  - 三种状态在主页卡片"开始/继续"按钮文案统一为"已结束"（PRD 的"项目完成后显示为暂停"的等价语义），点击进入任务页查看详情。

**已收到的 PRD 来源**（Notion）：
- 总目录 `MyCrew项目系统设计` — `https://www.notion.so/3578e10c17cc801b9df6e2e5888b6cff`
- 主页 PRD `35a8e10c17cc80d988b4c818b1213ff9`
- 任务页 PRD `35a8e10c17cc80cc9094ef9b5d0a32be`
- 团队页 PRD `35a8e10c17cc80299e7ef0e65864c17a`
- 设置 PRD `35a8e10c17cc809ea789c1cfe1995123`

**v3 与 v2 的关键差异**：
- 桌面壳层：**保留 Tauri，升级到 Tauri 2.x**（v2 失败的根因是当时紧耦合架构与 sidecar 集成不熟，而非 Tauri 本身缺陷；Tauri 2 在 2025–2026 已大幅成熟，包体积/内存/安全性更优，长期看是更现代的选择）
- 前端：保留 React + Vite + TS + Tailwind
- 后端：保留 Python FastAPI sidecar，但 **重新设计模块边界**，避免 v2 的耦合问题
- 核心修复：用 **领域驱动的事件总线** 取代 v2 的紧耦合 service ↔ harness 调用

> 参考文档：`F:\ClaudeData\MyCrew_v2\docs\IMPLEMENTATION_GUIDE.md`（仅作参考，不复用 v2 代码）。
> Figma 原型：`https://www.figma.com/design/1sr0yP4OSIpokBszeNkwYV/MyCrew?node-id=0-1`
> 四个主页面节点：主页 `5:25`、任务 `33:4683`、团队 `33:4685`、设置 `33:4684`。
> Figma 中存在的 `backup` 页不在本期范围（保留为占位帧，不实现路由）。

---

## 1. 架构总览

采用 **分层架构 + 事件驱动**，单进程组合模型：

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
│  │ Harness 状态机 / Planner / QA / 经验   │                   │
│  ├──────────── 端口层 (ports/) ──────────┤                   │
│  │ Repo 抽象 / LLM 抽象 / MCP 抽象 / 交互  │                   │
│  └──────────── 数据层 (infra/) ──────────┘                   │
│    SQLite / 文件系统 / MCP stdio·http / LLM HTTP             │
└─────────────────────────────────────────────────────────────┘
```

**核心架构原则**：
- **依赖倒置**：领域层定义 Port（接口），infra 层实现 Adapter；service 通过 Port 调用，便于替换/Mock。
- **单向事件流**：领域层产出 Domain Event → EventBus → WS Hub 推到前端；前端命令通过 REST 进入 service 层。
- **无人工 input()**：所有交互通过 WS 双向消息（`prompt.request` ↔ `prompt.response`）。

---

## 2. 模块清单

### 2.1 前端模块（renderer）

| 模块 | 职责 | 关键文件 |
|---|---|---|
| **layout** | 应用骨架：固定宽左导航（4 页面入口 + 主题切换 + 版本信息）、内容区、可折叠底部日志栏（多终端 tab） | `AppShell.tsx` `Sidebar.tsx` `LogDrawer.tsx`（含 tab 切换） |
| **page-home** | 主页：项目卡片网格（4×N 分页，最多 100 张/25 页）、MCP 连接条、Token 监控条、新建项目入口 | `pages/HomePage.tsx` `home/ProjectGrid.tsx` `home/ProjectCard.tsx` `home/McpStatusBar.tsx` `home/TokenBar.tsx` |
| **inception** | **建项目半页对话**（核心新增）：LLM 二级选择、思考开关、历史会话、新建会话、本地文件/目录索引、AI 拆解后的任务模块编辑（标题/详情/Agent/前置依赖） | `inception/InceptionDrawer.tsx` `inception/ChatPane.tsx` `inception/TaskBlueprintEditor.tsx` `inception/FileIndexer.tsx` |
| **page-task** | 任务管理：项目信息条（标题/进度/开始-暂停/路径/迭代占位）、DAG 蓝图（固定宽自适高，串联顶部对齐、并联上下排列）、任务窗口操作（编辑/暂停/重跑/Agent对话/查看输入输出） | `pages/TaskPage.tsx` `task/ProjectHeader.tsx` `task/Blueprint.tsx` `task/TaskNode.tsx` `task/AgentChatDrawer.tsx` `task/IoViewerDrawer.tsx` |
| **page-team** | 团队：顶部三 tab（**Agents / Crews / Tools** + 已有数量徽标）；左侧半页编辑器（新建/编辑/取消/保存/重置） | `pages/TeamPage.tsx` `team/AgentList.tsx` `team/CrewList.tsx` `team/ToolList.tsx` `team/EditorDrawer.tsx`（多形态：AgentForm / CrewForm / ToolForm） |
| **page-settings** | 设置：顶部三 tab（**LLM / MCP / 系统权限** + 已有数量徽标）；左侧半页编辑器；权限是文件/目录/命令/Git 白名单矩阵 | `pages/SettingsPage.tsx` `settings/LlmList.tsx` `settings/McpList.tsx` `settings/PermissionMatrix.tsx` `settings/EditorDrawer.tsx` |
| **stores（划分明确）** | **服务端状态走 React Query**（项目列表 / 任务 / MCP / LLM / 日志 / 配置等，由 WS 推送和 REST 拉取共同维护 cache）；**UI 状态走 Zustand**（抽屉开关 / 选中项 / 拖拽态 / 主题 / DAG 编辑暂存等）。命名规范：`useXxxQuery`（RQ） vs `useXxxStore`（Zustand）。 | `queries/use*Query.ts` `stores/use*Store.ts` |
| **net** | REST 客户端 + 单例 WS + 事件路由 | `net/api.ts` `net/ws.ts` `hooks/useEvent.ts` |
| **ui-kit** | 通用组件（Modal / Toast / StatusDot / Empty / Skeleton） | `components/ui/*` |

### 2.2 后端模块（backend）

| 层 | 模块 | 职责 |
|---|---|---|
| **api/** | `routes_project.py` `routes_task.py` `routes_mcp.py` `routes_llm.py` `routes_agent.py` `routes_config.py` `routes_log.py` `ws.py` | REST 路由 + WS Hub；只做参数校验与 service 调用，不写业务 |
| **services/** | `project_svc.py` | 项目 CRUD、复制（不带路径/进度）、删除（二次确认）、卡片分页、根目录绑定 |
| | `inception_svc.py` | **建项目对话**：管理立项会话、调用 LLM 拆解任务、本地文件索引（受权限服务约束）、按任务数选择执行结构（顺序/Crew/Flow）、调用 `agent_factory` / `crew_factory` Tool 动态生成缺失资源 |
| | `workflow_svc.py` | 启动/暂停/恢复 Harness；**暂停语义**：当前任务跑完，截断后续任务链；恢复从暂停点续跑 |
| | `mcp_svc.py` | MCP 服务器池：启动、心跳、工具列表缓存、强制全量重连（主页"连接"按钮） |
| | `llm_svc.py` | LLM 配置（名称/类型/API/URL/模型）、Token 用量轮询适配（百分比/M 数/可用性三态）、30s 自动+手动刷新 |
| | `agent_svc.py` | Agent 模板：角色名/目标/背景/能力（推理/重试/记忆/记忆库路径/思考模式）/工具绑定 |
| | `crew_svc.py` | **Crew CRUD**：队名/过程（顺序/层级）/角色（多 Agent 组合） |
| | `tool_svc.py` | **Tool CRUD**：扫描 `src/tools/` 自动发现、用户脚本登记、签名校验、Agent ↔ Tool 绑定 |
| | `permission_svc.py` | **系统权限白名单**：文件读写删/目录创建/命令执行/Git；统一配置文件 + 运行时拦截 |
| | `log_svc.py` | 日志查询、按 source（多终端 tab）分流、归档 |
| **domain/** | `harness/` | 项目运行状态机：`READY → RUNNING ⇄ PAUSED → (COMPLETED \| COMPLETED_WITH_WARNINGS \| COMPLETED_WITH_ISSUES \| ABORTED)`；DRAFT 阶段属于 inception_svc 不在此处。Task 级状态机另在 §4 `tasks.status`。纯领域逻辑、零 IO，所有副作用通过 Port |
| | `qa/` | DAG 健壮性校验（拓扑/引用完整性/连通性）+ Task 输出 schema 校验调度（实际 Pydantic 验证下沉到 infra） |
| | `experience/` | 经验库读写、tag 相关性匹配（CrewAI long-term memory 的领域抽象） |
| | `events.py` | Domain Event 定义（dataclass） |
> ※ 旧 v2 的 `planner/` 模块在 v3 已被 `inception_svc`（业务层）接管，不再保留为独立领域模块。
| **ports/** | `llm_port.py` `mcp_port.py` `repo_port.py` `interaction_port.py` `event_bus_port.py` | Protocol 接口；领域/服务通过这些类型依赖 |
| **infra/** | `llm/openai_adapter.py` `llm/anthropic_adapter.py` `llm/qwen_adapter.py` | LLM 实现 |
| | `mcp/stdio_client.py` `mcp/http_client.py` `mcp/pool.py` | MCP 连接实现 |
| | `repo/sqlite_repo.py` `repo/file_repo.py` | 持久化实现 |
| | `interaction/ws_interaction.py` | 通过 WS 收集用户回应（替代 input()） |
| | `event_bus/inproc_bus.py` | 进程内 pub/sub |
| **bootstrap/** | `container.py` | 依赖注入容器（手写 DI） |
| | `paths.py` | 路径常量集中处理 |
| | `app.py` | FastAPI 应用装配（lifespan、cors=loopback、router 注册） |
| | `main.py` | uvicorn 入口（含 --port、健康检查） |

### 2.3 Tauri 壳层模块（Rust）

| 模块 | 职责 |
|---|---|
| `src-tauri/src/main.rs` | App 生命周期、`tauri::Builder` 装配、单实例锁（`tauri-plugin-single-instance`）、窗口创建、菜单/托盘 |
| `src-tauri/src/sidecar.rs` | sidecar 启动（用 `tauri::api::process::Command::new_sidecar`）、端口探测/握手、stdout/stderr 转发、健康检查、退出码监听、指数退避重启 |
| `src-tauri/src/commands.rs` | `#[tauri::command]` 函数集合，仅本地能力：`pick_file` / `open_external` / `get_version` / `secret_set` / `secret_get`（业务全走 HTTP，不在此转发） |
| `src-tauri/src/lifecycle.rs` | 监听窗口关闭事件 → 调用后端 `/lifecycle/state` → 弹"运行中确认"窗 → 协调 shutdown sequence |
| `src-tauri/tauri.conf.json` | 窗口尺寸/sidecar 路径/权限 allowlist |
| `src-tauri/Cargo.toml` | Rust 依赖：tauri 2.x、tauri-plugin-single-instance、tauri-plugin-stronghold（凭证）、tauri-plugin-updater、reqwest（HTTP 探活） |

---

## 3. 通信契约

### 3.1 REST

- 基址：`http://127.0.0.1:18321/api/v1/`（仅监听 loopback）
- 统一响应：`{ ok: true, data }` / `{ ok: false, error: { code, message } }`
- 关键端点：
  - **立项对话**：`POST /inceptions`（开会话）/ `POST /inceptions/:id/messages`（发消息，SSE 流式回包）/ `POST /inceptions/:id/index-path`（索引本地文件目录）/ `POST /inceptions/:id/finalize`（确认 → 生成项目）/ `GET /inceptions`（历史会话）
  - **项目**：`POST /projects/:id/clone` / `DELETE /projects/:id`（含名称二次确认） / `PUT /projects/:id/root-path` / `POST /projects/:id/start` / `POST /projects/:id/pause` / `POST /projects/:id/resume` / `GET /projects?page=&size=4`
  - **任务**：`GET /tasks?project_id=` / `PUT /tasks/:id`（编辑详情，仅项目非运行态）/ `POST /tasks/:id/pause`（截断后续链）/ `POST /tasks/:id/rerun`（二次确认）/ `GET /tasks/:id/io?direction=in|out`（左拉半页输入输出查看）/ `POST /tasks/:id/intervene`
  - **MCP**：`GET /mcp/servers` / `POST /mcp/servers` / `POST /mcp/servers/:id/restart` / `POST /mcp/refresh-all`（强制全量重连） / `POST /mcp/internal/call`（loopback 限定，供 BaseTool 包装层调用，不暴露给 Agent）
  - **LLM**：`GET /llm/providers` / `PUT /llm/providers/:id` / `GET /llm/quota`（Token 用量，30s TTL 缓存）
  - **Agent / Crew / Tool**：`GET|POST|PUT|DELETE /agents` / `/crews` / `/tools`；`POST /tools/scan`（扫描 src/tools 目录）
  - **权限**：`GET /permissions` / `PUT /permissions`（白名单矩阵）
  - **日志**：`GET /logs?source=&level=&since=`（source 用于多终端 tab）
  - **配置**：`GET /config` / `PUT /config`（含主题）

### 3.2 WebSocket

- 端点：`ws://127.0.0.1:18321/ws`，单连接、双向。
- 消息：`{ type: string, ts: ISO8601, payload: object }`
- 事件类型分组：
  - `inception.*` — `inception.delta`（流式 token）, `inception.tasks_drafted`（AI 拆解结果）
  - `project.*` — `project.state_changed`, `project.progress`
  - `task.*` — `task.started`, `task.progress`, `task.completed`, `task.failed`, `task.paused`, `task.validation_failed`（含 schema 错误详情）
  - `mcp.*` — `mcp.connected`, `mcp.disconnected`, `mcp.tool_call`
  - `llm.*` — `llm.quota_changed`（百分比/M 数/三态可用性）
  - `tool.*` — `tool.scanned`（src/tools 目录变化）
  - `prompt.request` ↔ `prompt.response` — 替代 input() 的双向交互
  - `log.append` — 带 `source`（多终端 tab 来源）的实时日志推送

### 3.3 InteractionPort（人工介入抽象）

```python
class InteractionPort(Protocol):
    async def prompt_choice(self, ctx: PromptCtx, options: list[Choice]) -> str: ...
    async def prompt_text(self, ctx: PromptCtx, hint: str = "") -> str: ...
    async def prompt_confirm(self, ctx: PromptCtx) -> bool: ...
```
WS 实现：服务端发出 `prompt.request` 带 `request_id`，挂起 Future，前端用户操作后回 `prompt.response`，服务端 resolve Future。超时/断连有兜底。

---

## 4. 数据架构

**主存储：SQLite**（`data/db/mycrew.db`，aiosqlite + 简易 Repo 模式，不引入 ORM）

| 表 | 用途 |
|---|---|
| `projects` | 项目元数据：id, name, root_path（Agent 产出默认目录，不强制限制读写）, state, **is_running(bool)**（替代 state 中的 running 标识；当前 MVP 全局只允许一个 is_running=true，但 schema 不强约束，便于将来放开并发）, progress_pct, execution_kind(sequential\|crew\|flow), created_at, copied_from(可选) |
| `inception_sessions` | 立项对话：id, llm_id, thinking_mode, system_prompt, indexed_paths(JSON), created_at |
| `inception_messages` | 立项对话消息：id, session_id, role, content, ts |
| `tasks` | 项目下任务：id, project_id, title, detail, agent_id, **kind(regular\|final_qa)**, **output_schema(JSON Schema)**, status(pending\|running\|paused\|done\|failed\|aborted\|validation_failed\|blocked), deps(JSON), io_in_ref, io_out_ref, started_at, finished_at, qa_score |
| `agents` | Agent 模板：id, role, goal, backstory, reasoning, max_retry, memory_enabled, memory_path, thinking_mode, tool_ids(JSON), llm_id, is_auto_generated, promoted_at |
| `crews` | **Crew**：id, name, process(sequential\|hierarchical), agent_ids(JSON), **is_auto_generated**, **promoted_at** |
| `tools` | **Tool**：id, name, script_path, source(builtin\|user), checksum, params_schema(JSON) |
| `mcp_servers` | MCP 配置：id, name, transport(stdio\|http), command/args/url, env_ref(JSON, 引用 keystore), enabled, **discovered_tools(JSON：心跳时同步的 MCP 工具清单与 schema)** |
| `llm_providers` | LLM 配置：id, name, type(枚举: openai/anthropic/qwen/deepseek/gemini/ollama/custom), api_key_ref, base_url |
| `llm_models` | 模型清单（provider 一对多）：id, provider_id, model_name, label, max_tokens, supports_thinking |
| `app_settings` | 简单 key-value：`default_inception_model`、`default_agent_model`、`task_concurrency_limit`（默认 3）、主题、上次活动等 |
| `permissions` | **系统权限白名单**：id, kind(file_read\|file_write\|...), pattern, allowed |
| `chat_sessions` / `chat_messages` | Agent 对话历史（任务页失败介入对话用） |
| `logs` | 结构化日志：含 `source` 字段（多终端 tab 来源） |
| `prompt_audit` | 人工介入历史（request_id, ctx, user_response, latency_ms） |

**文件存储**：
```
data/
├─ config/app.yaml          # 用户配置（含加密 LLM key 的引用，不直接存 key 明文）
├─ db/mycrew.db
├─ logs/{YYYYMMDD}.jsonl    # 滚动日志
├─ cache/mcp_health/        # MCP 心跳缓存
└─ secrets/keystore.json    # OS keychain 失败时的回退（DPAPI 加密）
output/
└─ {YYYYMMDD_HHmm}_{Project}/  # CrewAI 运行产物
```

**敏感数据**（单一信源原则）：
- **Tauri Rust 主进程** 是凭证唯一持有者：用 **`tauri-plugin-stronghold`**（IOTA Stronghold，跨平台原生加密）作为主存；附加 **`tauri-plugin-keyring`** 作为可选项把主密码托管到 OS Keychain。失败时回退到 Windows DPAPI 加密的 `data/secrets/keystore.json`。
- **Python sidecar 不保存凭证**：每次需要时通过 `GET /internal/secrets/:key`（仅 loopback + 一次性 token 鉴权）从主进程拉取；用完即丢，不进日志、不进 DB。
- **前端**：永远只见掩码，写入新值时直接由 WebView 通过 `invoke('secret_set', ...)` 交 Rust 主进程入库，不经过 Python。

---

## 5. 技术选型与理由

| 层 | 选型 | 理由 |
|---|---|---|
| 桌面壳 | **Tauri 2.x（Rust）** | 包体积小（~10MB vs Electron ~80MB）、内存占用低、安全模型更严格；2025 后已具备 Electron 等价的 sidecar / 自动更新 / 凭证存储能力；与产品长期演进方向一致 |
| 前端框架 | **React 19 + Vite 6 + TS 5** | 团队熟悉、HMR 快、社区组件多 |
| UI 库 | **Tailwind 4 + Shadcn/ui** | Shadcn 已基于 Radix；按需 copy-in 组件、可控性强 |
| 国际化 | **i18next** | UI 主语言中文，预留 i18n 接口便于将来扩展 |
| 状态管理 | **Zustand + React Query** | Zustand 处理 UI/会话状态，RQ 处理服务端状态缓存 + 重试 |
| 后端框架 | **FastAPI + Uvicorn (single worker)** | 异步原生、Pydantic v2 校验、OpenAPI 自动生成；单 worker 因为是本地服务 |
| Crew 引擎 | **CrewAI 最新稳定版** | 项目核心定位 |
| MCP 客户端 | **官方 `mcp` Python SDK** | stdio + http 都覆盖 |
| 持久化 | **SQLite + aiosqlite** | 单机本地、零运维；显式 SQL，避免 ORM 复杂度 |
| 数据库迁移 | **Alembic（脚本式，不引入 SQLAlchemy ORM 模型）** | 用 Alembic 的 op.execute 写原生 SQL；解决"手写 SQL 无版本追溯"的问题；用户升级时按序应用迁移 |
| 加密 | **tauri-plugin-stronghold（Rust 主进程）+ DPAPI 回退** | Stronghold 是 Tauri 官方的跨平台凭证存储；不依赖第三方 npm |
| 日志 | **structlog（后端）+ tracing（Rust 主进程）** | JSON 行格式便于聚合 |
| 测试 | **pytest + pytest-asyncio（后端）+ Vitest + Playwright（前端 e2e）+ cargo test（Rust 壳）** | 标准选择 |
| 打包 | **PyInstaller（Python sidecar）+ Tauri build（NSIS / MSI 通过 Tauri bundler）** | Windows 一站式；Tauri 对 sidecar 二进制的 path-by-target 命名约定要遵守 |

> 不引入 K8s/Docker/MySQL/Kafka——产品是单机桌面应用，引入这些只会增加心智负担。"高可用"在本场景的含义是 **sidecar 健康检查 + 崩溃重启 + 状态可恢复**，而非集群。

> **关于 Tauri**：v2 弃用的根因是当时项目紧耦合架构与 sidecar 集成不熟，而非 Tauri 本身缺陷。Tauri 2.x（2025+）已具备 Electron 等价的 sidecar/自动更新/凭证存储/单实例锁等能力，且包体积、内存、安全模型显著优于 Electron。v3 选 Tauri 是技术正向选择，不是历史包袱。前端代码（React/Vite/Tailwind）与 Tauri 解耦，将来若极端情况下需要切换壳层，迁移成本主要在 `src-tauri/` 这一薄层。

---

## 6. 项目目录结构

```
MyCrew_v3/
├─ src-tauri/                 # Tauri Rust 壳层
│  ├─ src/
│  │  ├─ main.rs              #   App 装配 + 单实例
│  │  ├─ sidecar.rs           #   Python sidecar 生命周期
│  │  ├─ commands.rs          #   #[tauri::command] 集合（仅本地能力）
│  │  └─ lifecycle.rs         #   优雅关闭协调
│  ├─ tauri.conf.json         #   窗口/sidecar/权限 allowlist
│  ├─ Cargo.toml
│  └─ icons/
├─ frontend/                  # React 前端（Tauri 内嵌 webview 加载）
│  ├─ src/{pages,components,queries,stores,net,hooks,types,styles}/
│  ├─ vite.config.ts
│  └─ package.json
├─ backend/                   # Python sidecar
│  ├─ api/  services/  domain/  ports/  infra/  bootstrap/
│  ├─ migrations/             #   Alembic 迁移脚本（env.py + versions/，仅 op.execute 写原生 SQL，不开 autogenerate）
│  ├─ tests/
│  ├─ alembic.ini
│  └─ pyproject.toml
├─ src/                       # 用户可扩展源代码区（运行时被 backend 扫描加载）
│  ├─ tools/                  #   ★ 用户自定义 Tool 脚本（每个 .py 暴露 MANIFEST）
│  ├─ agents/                 #   （可选）用户预置 Agent 模板 YAML
│  └─ crews/                  #   （可选）用户预置 Crew 编排 YAML
├─ data/                      # 运行时数据（gitignored）
│  ├─ config/app.yaml         #   应用配置（含主题、窗口尺寸、上次打开项目等）
│  ├─ db/mycrew.db            #   SQLite 主库
│  ├─ logs/{YYYYMMDD}.jsonl   #   滚动日志
│  ├─ cache/mcp_health/       #   MCP 心跳
│  ├─ secrets/keystore.json   #   DPAPI 加密回退
│  └─ runtime/last_state.json #   异常退出前的运行态快照（启动时读取并提示恢复）
├─ output/                    # 项目产物（gitignored），按 {YYYYMMDD_HHmm}_{Project} 分目录
├─ docs/
│  ├─ ARCHITECTURE.md         # 本方案的固化版
│  ├─ API.md                  # OpenAPI 导出 + WS 事件清单
│  └─ ADR/                    # 架构决策记录
├─ scripts/                   # 启停 / 打包 / 数据库迁移
├─ .gitignore  .env.example  README.md  Description.md  meta.json
└─ assets/
```

> 项目命名应符合 `Claude-PascalCase` 规范（参考 `F:\ClaudeData\CLAUDE.md`），但用户已用 `MyCrew_v3`；保持现状，不在本次重命名以避免引入额外风险。

---

## 7. 实施路线图

按"可演示优先"原则，每阶段产出可运行的应用，下一阶段在前一阶段基础上叠加。本路线由 Agent 驱动研发，**不预估天数**，节奏由实施过程的反馈循环决定。

### Phase 0 — 工程脚手架
- 初始化项目（`pnpm create tauri-app` 模板基础上调整为 frontend / backend / src-tauri 三平行目录）
- 提交 v3 项目骨架到独立 Git repo（按 ClaudeData 规范）
- 配置 ESLint / Prettier / Ruff / cargo fmt / pre-commit hooks
- **撰写首批 ADR**（§16 列出的 001~008 全部落地为 `docs/ADR/000X-*.md`）
- **交付**：仓库初始化、Description.md、meta.json、README、ARCHITECTURE.md（本计划裁剪后版本）、ADR-001~008、能跑空 Tauri 窗口

### Phase 1 — 端到端骨架
- 后端：`bootstrap/`、`api/ws.py`、健康检查、空 service 占位、SQLite + Alembic 初始化（含首个 baseline 迁移）
- Tauri 主进程：sidecar 启动（`tauri::api::process::Command::new_sidecar` 配合 `tauri.conf.json` 中 `bundle.externalBin`）+ 端口握手 + 崩溃重启 + **优雅关闭协议**（§14.1）
- 前端：4 页路由 + 空布局 + WS 连接 + 底部日志栏（多 tab 占位）
- **IPC 集成测试套件**：脚本驱动跑 ① spawn → 握手成功 ② 后端 OOM/崩溃 → 主进程指数退避重启 ③ 用户关窗 → shutdown sequence 完成 → 无僵尸进程 ④ MCP 子进程关闭信号传播 ⑤ Alembic 升级回滚演练（**每个 migration 必须实现 `downgrade()` 函数**，CI 跑 `upgrade head → downgrade -1 → upgrade head` 三联回环验证）。CI 中作为 must-pass 检查。
- **交付**：双击应用 → 4 页可切换；关闭应用前端发起 Tauri Command → 后端落盘 → 进程退出；IPC 测试全绿

### Phase 2 — 配置/凭证存储与启动加载
- `routes_config.py` + `routes_llm.py` + `routes_mcp.py`（CRUD）
- 设置页 UI 占位：LLM/MCP/系统权限 三 Tab 框架
- **启动加载流程**（§17）：读 `app.yaml` → 检查 `last_state.json` → 提示恢复未完成项目
- **交付**：录入配置 → 关闭应用 → 重开后所有数据回归

### Phase 3 — MCP 连接池 + 首批包装 Tool
> **依赖关系**：Phase 3 仅建立 MCP 基础设施层（连接、健康、工具发现）+ 落地 1~2 个 MCP 的手写包装 Tool 作为示范模板。Phase 4 的 Harness 通过 `MCPPort` 消费 Phase 3 产出的池，并能用上至少一个真实 MCP 工具。
- `infra/mcp/`：stdio + http adapter；`pool.py` 生命周期、心跳、重连
- `mcp_svc`：启用/禁用、工具列表、状态变化广播；心跳同步 `discovered_tools` 到 DB
- 主页：MCP 状态条（单行+滚动+连接按钮）
- **关闭路径**：应用关闭时先发 stdio 关闭信号 → 等待 N 秒 → 强杀残余子进程
- **首批 MCP 包装 Tool 示范**（§11.6 落地）：
  - 选 2 个最常用 MCP（建议 `filesystem` + `blender` 或 `figma`，按用户需要可调）
  - 在 `src/tools/builtin/mcp_<server>/` 下为每个 MCP 工具写 BaseTool 子类，args_schema 严格按 MCP 官方文档对齐
  - 给出包装 Tool 的标准模板与代码注释，供后续扩展时遵循
  - 定义"生成包装骨架"按钮逻辑（基于 MCP `discovered_tools` schema 自动产 Pydantic 草稿）
- **交付**：MCP 在线/离线实时刷新；关闭应用不留僵尸子进程；首批包装 Tool 可被 Agent 实际调用

### Phase 4 — Harness 领域核心
- `domain/harness/`：纯状态机；所有 IO 通过 Port
- `domain/planner/`、`domain/qa/`、`domain/experience/`
- `infra/interaction/ws_interaction.py`：WS 双向 prompt
- `workflow_svc`：启动/暂停/恢复；状态变化每步落库
- **交付**：后端 CLI 可跑通最小项目（介入用脚本模拟）

### Phase 5 — 主页 + 项目立项对话（拆 3 子阶段，逐步降风险）

**Phase 5a — 主页 + 立项最小闭环（只读蓝图）**
- 主页项目网格、卡片操作（复制/删除/路径/开始）、MCP 条、Token 条
- 立项抽屉骨架：LLM 二级选择 + 思考开关 + 流式对话
- 后端 `inception_svc` 基础形态：调用 LLM、解析 JSON 蓝图、生成项目
- 任务蓝图右栏**只读展示**（不可编辑）→ 直接确认生成
- **交付**：能从对话产出一张可启动的项目卡，蓝图不可改

**Phase 5b — 蓝图可编辑 + 文件索引**
- 任务蓝图右栏可编辑（标题/详情/Agent/前置依赖）
- "让 AI 重新评估架构"按钮（触发 LLM 复核）
- 文件索引功能（小项目全文 / 大项目目录树+按需 file_read）
- 立项 Tool 集落地：agent_factory / crew_factory / list_* / file_indexer / file_read
- **交付**：可调整 AI 草案；可索引本地资料

**Phase 5c — 历史会话 + 草稿恢复**
- 左栏历史会话列表（含 [草稿] 标记）
- 关闭抽屉/应用时静默自动保存
- 上次中断的会话状态恢复（含输入框未发出的内容）
- **交付**：完整立项体验闭环

### Phase 6 — 任务页（核心交互）
- ProjectHeader（标题/进度/开始-暂停/路径/迭代占位）
- DAG 蓝图：TaskNode 操作菜单（编辑/暂停/重跑/Agent 对话/查看输入/查看输出）；Agent 变更下拉（项目运行中禁用）
- 暂停语义：任务级与项目级各自落地；rerun 二次确认
- **关闭保护**：项目运行中关闭应用 → 二次确认弹窗（"项目正在运行，关闭将暂停未完成任务并保存进度"）
- E2E：Playwright 跑完整工作流（建项目→启动→暂停→介入→完成→重开后状态恢复）
- **交付**：核心闭环跑通且支持崩溃恢复

### Phase 7 — 团队页（Agent / Crew / Tool）
- 三 Tab + 黄金分割侧边编辑抽屉
- Agent 能力字段（推理/重试/记忆/记忆库路径/思考模式/工具）
- Crew 编排（队名 / 过程 / 角色）
- Tool 扫描 `src/tools/`；插件协议落地（§12）；首次加载弹窗确认
- **交付**：可创建团队、绑定到项目

### Phase 8 — 设置页 + 系统权限
- LLM / MCP / 系统权限 三 Tab；权限白名单矩阵
- `permission_svc` 拦截器接到所有 Tool/MCP 实际调用
- **交付**：权限切换实时生效

### Phase 9 — 打磨与打包
- 主题切换、版本号、空状态、loading、错误兜底
- PyInstaller 打包后端为单文件二进制 → 拷到 `src-tauri/binaries/{target-triple}/mycrew-backend.exe` → `cargo tauri build` 出 NSIS / MSI 安装包
- 自动更新（可选，`tauri-plugin-updater`）
- **交付**：可分发的 `.exe` / `.msi`，覆盖安装、卸载干净

---

## 8. 高可用与可观测性（本地版）

不需要集群，但要做到：
- **崩溃自愈**：Tauri 主进程通过 `Command::spawn` 返回的 `CommandChild` 监听 `CommandEvent::Terminated`，退出码 ≠ 0 → 指数退避重启（最多 3 次），失败后弹错误页 + "导出诊断包"
- **状态可恢复**：每次状态机转移落库（`projects.state` + `tasks.status`），重启后 `workflow_svc.recover()` 扫描"运行中"项目并提示用户继续/丢弃
- **资源监控**：主进程定期采集 sidecar CPU/内存 → WS 推到状态条
- **诊断包导出**：一键打包 `data/logs/` + 配置（脱敏） + 系统信息 → `.zip`，方便上报问题
- **MCP 故障隔离**：单个 MCP 崩溃不影响其他；用户可在主页一键重连

---

## 9. 验证方案

每阶段结束执行：
1. **Backend**：`cd backend && pytest`（单元 + Port Mock 集成测试）
2. **Renderer**：`cd frontend && pnpm test`（Vitest 组件测试）
3. **E2E**：`pnpm e2e`（Playwright 启动应用，跑 4 页冒烟 + Phase 5 的完整工作流脚本）
4. **手动冒烟清单**（每阶段一份 checklist，放入 `docs/dev-notes/phase-{n}.md`）：
   - 启动应用 → 4 页可切换 → 关闭后无残留进程
   - MCP 在线/离线切换 → 主页指示器实时更新
   - 录入错误 LLM key → 显示明确错误 → 不闪退
   - Phase 5+：完整跑一次"指令文件 → Planner → 审批 → 执行 → QA → 完成"

---

## 10. 关键交付物清单

| 类别 | 文档/产物 | 阶段 |
|---|---|---|
| 架构 | `docs/ARCHITECTURE.md`（本方案的固化版） | Phase 0 |
| API | `docs/API.md` + 自动生成的 OpenAPI JSON + WS 事件清单 | Phase 1 起持续更新 |
| ADR | `docs/ADR/001-credentials.md`、`002-event-bus.md`、`003-interaction-port.md` 等 | 各阶段决策时 |
| 部署 | `docs/BUILD.md`（开发启动 + 打包流程） | Phase 0 / Phase 7 |
| 用户 | `docs/USER_GUIDE.md`（首次使用 / MCP 配置 / 故障排查） | Phase 7 |
| 项目元 | `Description.md`、`meta.json`、`README.md` | Phase 0 |

---

## 11. PRD 对齐细节（已落地，等实施）

PRD 关键交互全部对齐进上面架构。本节做行为级澄清，避免实施期歧义。

### 11.1 全局框架
- **左侧栏**：固定宽度（约 200px），垂直排列：Logo / 4 页面入口（主页/任务/团队/设置）/ 主题切换（日夜）/ 版本号。
- **底部日志栏**：默认收起，仅显示后端最后一行；点击展开 → 多终端 Tab（每个 MCP 一个 tab + "应用日志" tab + "Agent 输出" tab），右上角"收起"按钮；只读、不写。

### 11.2 主页
- **新建项目入口** → 从左侧拉出"半页"抽屉（黄金分割宽度，约 37% 屏宽，可由用户拖拽调节并记忆）：
  - 顶部：LLM 二级选择（Provider → Model）+ 思考模式开关（仅当所选 model `supports_thinking=true` 时启用）；预选值取 `default_inception_model`。
  - 左栏：历史会话列表（每项对应一个 project，带 project 名 + 状态徽标；未 finalize 的草稿带"[草稿]"标记）+ "新建会话"；关闭抽屉/应用时草稿静默自动保存，下次打开恢复至上次状态；抽屉顶部提供"丢弃草稿"按钮供主动清理。
  - 中栏：消息流 + 输入框 + "索引文件/目录"按钮（可多次添加，已加列表显示在输入框上方可移除）。
  - 右栏：AI 拆解出的任务模块（可编辑：任务标题/详情/Agent/前置依赖；右上角"让 AI 重新评估架构"按钮触发 LLM 复核 sequential/Crew/Flow 选择）。底部"确认 → 生成项目卡"。
- **文件索引策略（自动）**：
  - 选中文件/目录 → 后端用 `file_indexer` Tool 估算总字节。
  - **小项目（≤ 200KB 或 ≤ 50 文件）**：全文读入，按文件名分块作为 `<file path="...">{content}</file>` context block 注入 LLM 上下文。
  - **大项目**：仅注入目录树（`tree -L 3` 形式 + 文件大小），LLM 在对话中按需调 `file_read(path)` Tool 取具体文件内容（按 token 预算累加）。
  - 索引内容受 §11.5 系统权限约束（"文件读取"开关关闭时整个功能禁用）。
- **项目卡片网格**：分页 4 张/页，最多 100 张/25 页；选中态边缘发光。
- **同时只能运行一个项目**：当已有项目处于 running 时，点击其他项目"开始/继续" → 弹出"请先暂停当前运行项目 X，是否暂停并切换？" 用户确认后自动 pause 当前 + start 新的。
- **卡片元素**：标题 / 复制按钮 / 删除按钮（弹窗输入项目名二次确认）/ 创建日期 / 进度（按已完成任务数计算百分比）/ 开始按钮（进度=0）或继续按钮（进度>0；二者都需先配根目录）/ 路径按钮（执行后只能"打开文件管理器"）/ 迭代按钮（占位无功能）/ 任务子列表（仅展示标题+Agent+换 Agent 下拉）。
- **复制项目语义**：
  - **复制**：task 结构（标题/详情）、依赖关系、Agent 绑定、Crew/Flow 架构选择、`execution_kind`。
  - **不复制**：`root_path`、所有任务的 status/progress/qa_score/IO 引用、关联的 inception session。新项目状态为"未启动"，需用户重新配根目录。
- **MCP 连接条**：单行横向滚动；底层 30s 心跳；右侧"连接"按钮 → 强制全量重连+刷新。
- **Token 监控条**：单行横向滚动；30s 自动刷新 + 手动刷新按钮；显示规则：返回百分比 → 整数百分比；返回 token 数 → 单位 M 整数；其他 → 绿点(可用)/红点(不可用)。

### 11.3 任务页
- **项目信息条**：标题 / 进度 / 开始(暂停) / 路径 / 迭代占位。
- **暂停语义**：当前正在跑的任务**不强杀**，跑完后截断后续链；恢复时从暂停点继续。
  - **强制中断兜底**：项目状态条上"暂停"按钮旁显示进度提示（"正在等待 Task X 完成…{已耗时}"）；若用户长时间等不及，提供"强制中断"按钮（二次确认弹窗），点击后立即抛断 LLM 调用、当前 Task 标记为 `aborted`，下次"继续"时该 Task 重跑。
- **项目完成态**：所有链路完成且通过 final QA → 状态显示为"暂停"（与人工暂停外观一致，但带完成标记）。
- **DAG 蓝图**：窗口固定宽自适高；串联任务顶部对齐、并联任务上下排列；曲线连接。
- **任务结构编辑**（仅项目处于暂停态时可用）：
  - 蓝图右上角"+ 新增任务"按钮；点击后空白节点出现，可设置标题/Agent/详情；
  - 节点右键"删除任务"（已完成的任务不可删，只能重跑）；
  - 节点之间拖拽连线即设置依赖；点击连线再确认可删除依赖；
  - 编辑会重新计算 DAG 并落库。
- **任务窗口元素**：任务标题 / **Agent 信息 + Agent 变更下拉**（项目运行中整个项目禁用此变更，与 PRD 一致；项目暂停态可改）/ 任务进度 / 任务详情 / 更多操作菜单。
- **任务窗口操作菜单**：
  - 编辑详情（项目运行中禁用）
  - 任务级开始-暂停：无法暂停已开始/已完成的任务；暂停=任务链断点（此任务及后续不执行）；项目运行中被暂停的任务不允许立刻"打开"，需项目级暂停后再手动打开。
  - 重新执行：仅"已完成且非运行中"可用，二次确认弹窗中含选项【级联重跑下游（默认勾选） / 仅本节点】。"级联"会把所有依赖此节点的下游任务（递归）一并重置为 pending，下次启动时按 DAG 重跑。
  - **schema 演进 + rerun 协同规则**：始终以"当前最新"的 `output_schema` 为校验准；rerun 一个 task 时若其 schema 自上次完成后被改过，新输出按新 schema 验。**已完成下游 task** 之前用了旧 schema 输出 → rerun 弹窗自动勾"级联重跑下游"且不可取消；若用户只想重跑本节点（不级联），必须先把下游手工拨回 pending，承担"下游用了旧契约"的风险。
  - 打开与 Agent 的对话窗口：仅任务失败/不可执行时可用，下方面板嵌入（输入框 + 反馈框，参考原型 Task4）。**会话延续失败那次的 Agent 上下文**（含原 prompt、所有 LLM/Tool 交互、失败原因），用户每条发言作为新一轮 user message 注入；下一轮 Agent 在此基础上重试。重试成功则 Task 标 done，下游可继续；重试失败则保留对话留待下一次介入。
  - 查看输入信息 / 查看输出信息：左拉半页（黄金分割宽度），**两个 Tab**：
    - **Tab 1：结构化数据**——按 `output_schema` 渲染表单/树形视图（键值清晰可读），输入 = 上游 Task 的 `output_schema` 实例化对象，输出 = 本节点 `output_schema` 实例化对象。
    - **Tab 2：原始过程**——Agent 完整聊天记录 + LLM 调用 trace + Tool 调用 trace（Markdown），用于深度调试。
  - IO 数据存储：结构化数据存 `output/{project}/{task_id}/{in,out}.json`；原始过程存 `{in,out}.md`；DB 只存路径引用。

### 11.4 团队页
- **顶部三 Tab**：Agents / Crews / Tools，每 Tab 标题带数量徽标。
- **左侧半页编辑器**：右上角"重置"按钮（清空回初始空态）+ 取消 + 保存。
- **Agent 表单**（PRD 字段语义已对齐）：
  - **角色名** / **目标** / **背景**（free text）。
  - **能力**：
    - `enable_reasoning`（boolean，对应 CrewAI `Agent.reasoning`）—— PRD "推理能力"。
    - `max_retry`（int，默认 3）—— PRD "最大重试次数"。
    - `memory_enabled`（boolean）+ `memory_path`（dir，默认 `data/memory/{agent_id}/`）—— 走 CrewAI 内建 long-term memory。
    - `thinking_mode`（boolean）—— UI 上仅当所选 LLM model 的 `supports_thinking=true` 时启用，否则灰显并提示"当前模型不支持思考模式"。
  - **工具**（多选自 Tools tab，**包含手写的 MCP 包装 Tool**；Agent 不直接绑 MCP 服务器）。
  - **LLM**（从设置页配置中选一个 provider+model）。
  > **PRD 未列字段补全**：LLM —— Agent 必备运行时依赖，PRD 未列已补齐。
  > **不绑 MCP 服务器的原因**：MCP 服务器在 v3 中是"后台资源"，由 mcp_svc 启动并提供进程；Agent 调用 MCP 工具时统一走 `src/tools/builtin/mcp_<server>/` 下的手写 BaseTool 包装（详见 §11.6），契约 100% 显式，避免 v2 因 dynamic MCP 包装失准导致的参数报错。
- **Crew 表单**：队名 / 过程（sequential / hierarchical，初版可只支持 sequential，hierarchical 标"实验性"）/ 角色（从 Agents 多选）。
- **Tool 表单**：提示文案"建议将脚本统一放在 `<MyCrew 根目录>/src/tools/` 下，系统将自动扫描并加载" / 名称 / 脚本路径（带"扫描 src/tools"快捷按钮）/ 来源标记（builtin / user）。
  - 用户脚本接口约定：每个 `.py` 文件应导出一个 `crewai.tools.BaseTool` 的子类，并定义 `args_schema`（Pydantic）。后端启动 + 用户点"扫描"时，遍历 `src/tools/`，import module → 找 `BaseTool` 子类 → 把 `args_schema` 转成 JSON Schema 入 `tools.params_schema` 字段，前端表单据此生成 Tool 详情视图。
  - 加载安全：首次发现新 Tool 时弹"信任并加载"二次确认；checksum 变更后再次弹窗。
- **列表区**：每行只展示关键信息 + 操作按钮（编辑/删除）。

### 11.5 设置页
- **顶部三 Tab**：LLM / MCP / 系统权限，每 Tab 标题带数量徽标。
- **LLM 表单**（一条记录 = 一组 provider+key，下挂一对多 model）：
  - **基础**：名称 / 类型（枚举：openai / anthropic / qwen / deepseek / gemini / ollama / custom）/ API Key / Base URL（custom 与 ollama 必填，其他可选用于代理转发）。
  - **模型清单**（同一表单内嵌多行编辑器）：每行 = `model_name`（自由文本，如 `gpt-4o`、`claude-opus-4-7`）+ 显示标签 + 最大 token + 是否支持思考模式。
  - Key 入库走主进程 keytar，前端只见掩码；编辑时显示"已设置，留空保留"。
- **LLM 选择控件**（出现在 Agent 表单、立项对话顶部、其他需要选 LLM 的地方）：二级下拉【Provider 记录 → 该 provider 下的某个 model】。
- **双默认 LLM**：LLM Tab 顶部有两个独立的"默认设置器"：①**立项默认**（新建立项会话时预选）②**Agent 默认**（新建 Agent 时预选）。两者都是可空的"指向某条 (provider, model) 组合"的指针，存于 `app_settings` 表（key-value：`default_inception_model`, `default_agent_model`）。用户可以随时改。
- **MCP 表单**（"协议"字段切换字段集）：
  - **基础**：名称 / 协议（stdio / http）/ 启用开关 / 自动启动开关（应用启动时是否拉起）。
  - **stdio 协议字段**：脚本路径（推荐用文件选择器）+ Args（动态多行）+ Env（动态键值对，每行可标记"敏感"，敏感值走主进程 keytar 加密）。
  - **http 协议字段**：URL + Headers（动态键值对，可标"敏感"，同上）。
  - **公共**：超时（秒，默认 30）、重连退避策略（指数/固定）。
- **系统权限**：9 个全局布尔开关：文件读取 / 文件写入 / 文件删除 / 文件修改 / 文件夹读取 / 目录创建 / 命令执行 / 后台命令 / Git 操作。默认全开（保证开箱即用），用户可取消。**当前为个人单机使用，不限制路径、不弹审批窗**；权限检查只在 Tool/MCP 真正调用时按"是否被禁用"短路返回。
  > **未来对外开放时的硬化路线**（保留备注，不在 MVP 实现）：①路径白名单（限制写入到 `<root>/output/**` 与 `data/**`）②高风险操作（命令执行/Git）按需弹审批 ③风险分级与审计日志 ④进程级沙箱（Job Object / cgroup）。
- **统一抽象**：LLM/MCP/Tool 三者均遵循"前端表单元数据 + 后端注册脚本"插件协议（见 §12）。

### 11.6 MCP 工具包装层（v2 痛点 ② 直接对应）

**问题诊断**：v2 直接把 MCP 服务器动态注入 CrewAI Agent，Agent 在调用 MCP 工具时参数频繁报错。根因是 CrewAI 对 MCP 工具描述的动态包装在边界场景（联合类型/嵌套对象/枚举/可选必选混合）失准。

**v3 设计**：

- 不依赖 CrewAI 的 dynamic MCP integration。
- 每个常用 MCP 工具（如 Blender 的 `execute_blender_code`、Figma 的 `get_design_context` 等）写一个**手工 CrewAI BaseTool 子类**，放在 `src/tools/builtin/mcp_<server>/`。
  - `args_schema`（Pydantic）严格按 MCP 官方文档定义；参数错误在 Pydantic 校验阶段就被拦截，错误信息精确指出哪个字段不对。
  - 内部调用 `mcp_pool.call(server_id=..., tool_name=..., validated_args=...)`。
  - 返回值做格式归一化（统一为字符串或固定 dict 形态），下游解析无歧义。
- `mcp_svc` 只负责"启动 MCP 进程 + 心跳"，不直接和 Agent 打交道。
- 这些包装 Tool 在团队页 Tools tab 中以 builtin 徽章列出，Agent 表单像选普通 Tool 一样选它们。
- **新增 MCP 服务器时的工作流**：用户接入新的 MCP 服务器 → 阅读官方文档 → 在 `src/tools/builtin/mcp_<server>/` 下写包装 Tool → 团队页扫描可用 → Agent 绑定。包装 Tool 与 MCP 工具一对一对应，**契约 100% 显式可审计**。
- **裸工具策略（严控）**：MCP 服务器实际提供的工具中，**只有被手写包装过的子集对 Agent 可见**。其余裸工具一律隐藏，避免 v2 同款"参数报错"问题复发。
  - mcp_svc 在心跳时同步 MCP 工具清单到 DB（`mcp_servers.discovered_tools` JSON）。
  - 团队页 Tools tab 在每个 MCP 子目录的标题行显示 `已包装 K / 已发现 N`，未包装的用灰色文字列出工具名 + 一键"生成包装骨架"按钮（基于 MCP schema 自动生成 Pydantic args_schema 草稿，用户审改后入库）。
  - **未包装的工具不进入** `agent_svc` 注入到 CrewAI Agent 的 tools 列表。

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

### 11.7 Task 输出契约（v2 痛点 ③ 直接对应）

**问题诊断**：v2 任务间用 free text 传递，下游 Agent 自行解析，错了不知道哪错。

**v3 设计**：每个 Task 必须有 `output_schema`（JSON Schema 形式存于 `tasks.output_schema`）。

**生成与编辑**：
- 立项 LLM 生成任务蓝图时，**为每个 Task 同步输出 `output_schema_json`**（也作为 §11.2 的 JSON 蓝图的一部分）。
- **schema 合法性校验**：后端在解析蓝图时，对每个 task 的 `output_schema` 用 jsonschema 库验证是否为合法 JSON Schema。不合法 → 把错误信息以 system message 形式喂回 LLM 并请其修正，最多 3 次；3 次仍失败则该 task 的 schema 退化为 `{}`（free text），同时在立项对话面板里给用户红色提示"task X 的输出契约未能生成，已退化为自由文本，建议手动补充"。
- **DAG 健壮性校验**（finalize 阶段同期执行）：后端做 ① 拓扑排序（检测环路）② 引用完整性（每个 deps 中的 task_id 都存在）③ 连通性（不存在孤立节点；至少有一个 entry 节点 deps=[]）。任何一项不通过 → 把诊断信息喂回 LLM 修正，最多 3 次；仍不行则**阻断 finalize**，前端面板提示"任务图谱有结构问题，请手动调整下面 N 个节点的依赖"，列出具体异常项让用户修。这是硬错，不退化。
- 任务蓝图编辑器右栏的 Task 卡新增"输出契约"分区，可视化展示 schema；用户可直接编辑（增删字段、调类型、改描述）。

**运行期校验**：
- Agent 执行完 → 拿到 free text 输出 + 完整聊天记录。
- `workflow_svc` 调用 **该 Task 所绑 Agent 的同一个 LLM**（不另设提取模型，保持语义同源、不额外增加配置）做 **structured output 提取**：把 free text 抽成符合 `output_schema` 的 JSON。
- Pydantic 验证通过 → Task `done`，结构化对象写入 `out.json`、原始过程写入 `out.md`。
- **下游 Task 的 input 组装**：`workflow_svc` 将下游 Task 所有 deps 的 output 按 `{upstream_task_id: <其 output_schema 实例>}` 字典形式组装传入。`agent_svc` 把这个字典作为 CrewAI Task 的 `context` 注入到 Agent 的提示词中（带每个上游 task 的 title 与 schema 字段说明），下游 Agent 在生成时可显式引用 `task_X.field_Y`。
- **多上游汇聚的等待语义（fork-join）**：下游 Task 严格等待 **所有** deps 完成（state=`done`）后才进入 ready 队列；任一 deps 处于 `failed`/`validation_failed`/`aborted` → 下游 Task 自动标 `blocked`，等用户解决上游后手动重试或级联恢复。这是 DAG 默认行为，不可选并行启动。
- Pydantic 验证失败 → Task 自动重试（重新跑 Agent + 二次提取），重试次数计入 `Agent.max_retry` 预算（与运行异常同权重）；预算用完后 Task 标 `validation_failed` → 进入"失败介入"流程（§11.3），用户在 Agent 对话窗口里看到具体哪个字段不符，补充提示让 Agent 重试。用户对话窗口的人工介入重试**不再计入** max_retry。
- **重试时的 LLM 上下文（累积式）**：每次自动重试 = 原 prompt + 上次 Agent 输出 + 上次异常/验证报错（具体字段错位详情）+ 重新生成指令。Agent 能"看到"上次哪里出了问题，避免循环犯同一错。token 成本随重试次数增长，max_retry 默认 3 次也是这条考虑下的折中。

**事件**：
- `task.validation_failed` WS 事件，携带验证错误详情，前端在 DAG 节点上以橙色高亮 + 弹通知。

**降级**：
- 若用户在 Task 卡里把 `output_schema` 设为 `{}`（空对象）→ 退化为 free text 模式（v2 行为），不做校验；用户应理解风险。
- 退化下 `out.json` 仍写入（值为 `{"_raw": "<agent free text>"}` 包装一层，保持 JSON 文件格式一致），但下游 Task 的 input 字典里 `input[upstream_id]` 直接是 **free text 字符串本身**（不是包装 dict），简化下游 Agent 提示词处理。退化模式不影响该上游 Task 的"任务页查看输入/输出"双 Tab 展示（Tab 1 显示 `_raw` 单字段，Tab 2 仍是聊天记录）。

### 11.8 数据流总览（关键路径）

1. **建项目**：用户对话 → `inception_svc` 调 LLM → 流式 `inception.delta` → AI 输出任务草案 `inception.tasks_drafted` → 用户编辑 → `POST /inceptions/:id/finalize` → `project_svc` 生成项目卡。
2. **跑任务**：用户点开始 → `workflow_svc` 启 Harness → 状态机驱动 → 每步发 `task.*`/`project.progress` → 失败时发 `prompt.request` 等用户介入。
3. **暂停**：前端 `POST /tasks/:id/pause` → `workflow_svc` 标记任务+下游 paused → 当前任务跑完不再调度后续。

后端事件契约已为以上路径全部预留，无遗漏。

## 12. Tool 扩展协议（仅 Tool）

> **简化范围**：原方案把 LLM / MCP / Tool 抽象到一个 PluginRegistry，是 MVP 过度设计。LLM 是固定枚举 + 1 个 custom adapter，MCP 走标准 MCP SDK，二者都不需要"扫描发现"。**只有 Tool 真需要动态加载**。
> 将来若加第三方 LLM provider 插件再升级到统一抽象。

**用户 Tool 加载流程**：

1. 启动期 + 用户在团队页点"扫描 src/tools" → `tool_svc.scan(Path("src/tools"))`：
   - 遍历 `*.py`，`importlib.import_module(rel_path)`
   - 反射查找模块顶层的 `crewai.tools.BaseTool` 子类
   - 读取类的 `name` / `description` / `args_schema`（Pydantic）→ 转 JSON Schema 入 `tools.params_schema`
   - 计算 SHA256 入 `tools.checksum`
   - 入库时若同名 Tool 已存在但 checksum 变化 → WS 发 `tool.changed` 事件，前端弹"已更新，是否信任新版本？"
2. 首次发现新 Tool → `tool.discovered` 事件 → 前端弹"新发现 Tool 'X'，是否信任并加载？"
3. Agent 执行时，`agent_svc` 把 Agent.tool_ids 关联的 Tool 类实例化注入 CrewAI Agent，与 MCP 动态发现的 tools 合并。

**安全**：
- 加载发生在 sidecar 进程内，无独立沙箱（个人单机用，§11.5 决策）。
- 文件操作受系统权限开关短路控制。
- 未来对外开放时，用 subprocess + 资源限制再加一层（§11.5 硬化路线已记）。

## 13. 前后端交互简图（说明 PRD 落地）

```
┌──────────────────────────────────────────────────────────────┐
│ 主页                                                         │
│ ┌─[新建项目]→拉出半页────────────┐                           │
│ │ ChatPane │ TaskBlueprintEditor │  POST /inceptions/*      │
│ └──────────┴─────────────────────┘  WS inception.*          │
│                                                              │
│ ┌────────── ProjectGrid (4×N 分页) ──────────┐              │
│ │ [复制][删除][路径][开始/继续][迭代]          │              │
│ └─────────────────────────────────────────────┘              │
│ ─ MCP 连接条（单行+滚动+连接按钮） ─                          │
│ ─ Token 监控条（单行+滚动+刷新按钮） ─                        │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ 任务页                                                       │
│ ProjectHeader：标题 / 进度 / 开始-暂停 / 路径 / 迭代          │
│ ┌── DAG 蓝图 ───────────────────────────────────────┐        │
│ │  [TaskNode] ─── [TaskNode] ─── [TaskNode]         │        │
│ │      │              ┴──────────[TaskNode]         │        │
│ └────────────────────────────────────────────────────┘       │
│ 节点菜单：编辑/暂停/重跑/Agent对话/查看输入/查看输出           │
└──────────────────────────────────────────────────────────────┘
```

## 14. 关闭与启动生命周期

### 14.1 优雅关闭（用户主动关窗 / 系统关机）

**触发**：用户点窗口关闭按钮、系统注销、托盘退出。

**关闭决策树**（Tauri 主进程主导，监听 `window.on_window_event(WindowEvent::CloseRequested)` 拦截默认关闭）：
```
窗口关闭信号
   │
   ├─ 检查后端：GET /lifecycle/state
   │    response: { running_projects: N, active_tasks: M, mcp_count: K }
   │
   ├─ N>0 → 弹出"二次确认"模态：
   │    "有 N 个项目正在运行，关闭将暂停未完成任务并保存进度。是否继续？"
   │    [继续关闭] [取消]
   │
   └─ 确认 → 进入"shutdown sequence"
```

**Shutdown sequence**（按序执行，每步带超时）：
1. **暂停所有运行中项目**：`POST /lifecycle/pause-all` → `workflow_svc` 标记所有 running 项目为 paused，截断后续链；正在跑的任务尽量等其完成（最多 30s 超时）
2. **持久化运行态**：把内存中未落库的进度、Agent 上下文、未消费的 prompt request 写入 `data/runtime/last_state.json`
3. **关闭 MCP 子进程**：`mcp_svc.shutdown_all()` → 每个 MCP 发 stdio 关闭信号 → 等待 5s → 强杀残余
4. **flush 日志与 DB**：commit 所有事务，关闭 SQLite，flush 日志缓冲
5. **后端进程退出**：返回 200 → Tauri 等 sidecar 自然退出，超时（10s）则强杀（`Child::kill()`）
6. **窗口关闭**：调用原 close 流程，主进程随之退出

**异常关闭兜底**：Tauri 主进程监听到 sidecar `on_event(CommandEvent::Terminated)` 时，立即把"崩溃前最后一次 task 状态变更"标记为 `crashed_unsaved`，下次启动告诉用户哪些任务可能需要重跑。

### 14.2 启动加载顺序

**冷启动**（双击应用图标）：
1. Tauri 主进程启动 → 单实例锁（`tauri-plugin-single-instance`）→ spawn Python sidecar → 端口握手
2. 后端 `bootstrap/app.lifespan`:
   - **STEP 1** 加载 `data/config/app.yaml`（含主题、窗口尺寸、上次打开页）
   - **STEP 2** 初始化 SQLite + 跑迁移
   - **STEP 3** 加载所有静态配置：`llm_providers` / `mcp_servers` / `agents` / `crews` / `tools` / `permissions`
   - **STEP 4** 扫描 `src/tools/` 注册用户插件
   - **STEP 5** 检查 `data/runtime/last_state.json`：
     - 存在且含 paused/running 项目 → 通过 WS 发 `lifecycle.recovery_prompt` → 前端弹窗"上次有 X 个项目未完成，是否恢复？"
     - 用户选恢复 → 把这些项目状态改回 paused（待用户手动点继续）；选丢弃 → 标记为 `aborted`
   - **STEP 6** 按 `app.yaml` 的"上次活动 MCP 列表"自动启动 MCP 池（用户曾启用的）
3. 前端连接成功 → 拉取项目列表、MCP 状态、LLM 配额 → 渲染主页

**重要约束**：
- 启动期间前端显示"正在恢复上次会话…"骨架屏，禁止操作
- 任何一步失败都回退到"安全模式"：不加载用户插件、不连接 MCP，让用户手动排查
- 启动总时长目标 < 3 秒（不含 MCP 实际握手）

### 14.3 项目数据的存储与恢复

数据所在层（与 §4 数据库表对应）：

| 数据 | 存储位置 | 持久化时机 | 启动时加载方式 |
|---|---|---|---|
| LLM/MCP/Agent/Crew/Tool/Permission 配置 | SQLite 各 `*_providers`/`*s` 表 | 用户保存时 | STEP 3 全量加载到内存缓存 |
| 项目元数据 | `projects` 表 | CRUD 时 | 进主页时按需分页查询 |
| 项目根目录 / 任务列表 / DAG 结构 | `tasks` 表 + `data/projects/{id}.dag.json` | 立项 finalize 时一次写入 | 进任务页时加载 |
| 任务运行进度 | `tasks.status` + `tasks.progress` | 每次状态变化立即落库 | 进任务页时加载，DAG 渲染当前态 |
| Agent 中间产物（IO） | `output/{project}/{task_id}/in.json,out.json` | task 启动/结束时落盘 | "查看输入/输出"按需读 |
| 立项对话历史 | `inception_sessions` + `inception_messages` 表 | 每条消息 commit | 主页"历史会话"列表显示 |
| 应用窗口/主题/最近项目 | `data/config/app.yaml` | UI 操作时 debounce 写 | STEP 1 加载 |
| 异常退出快照 | `data/runtime/last_state.json` | shutdown step 2 + 周期 60s | STEP 5 检查并询问 |
| LLM/MCP 凭证 | Tauri Stronghold + DPAPI 回退 | 用户保存时 Rust 主进程写 | 后端按需通过 loopback HTTP + 一次性 token 拉取 |

**写入策略**：
- 关键状态（task.status / project.state）→ **同步落库**，先 commit 再发事件
- 高频更新（task.progress %）→ **节流写库**（每 2s 或 5% 变化），但内存里始终最新值通过 WS 推送
- 文件型大对象（IO）→ 不入 DB，存 `output/`，DB 只存路径引用

## 15. 开发体验（DX）

- **Sidecar 热重载**：开发模式下 Tauri 主进程读到 `MYCREW_DEV=1` → 不走 sidecar bundle 路径，直接 spawn `uvicorn --reload`，监听 `backend/` 变更自动重启；前端 Vite HMR 独立工作。
- **同时启动**：`pnpm tauri dev` 自带前端 Vite + Tauri 主进程的并发；外加 `concurrently` 跑 `uvicorn`，整合到 `pnpm dev` 一条命令。
- **日志聚合**：开发期 Tauri 主进程把 sidecar stdout/stderr 用 `tracing` 打到控制台，并通过 Tauri Event 推到前端 DevTools，便于单窗口排查。
- **Mock 模式**：`MYCREW_MOCK=1` 环境变量下，所有 Port 替换为 Mock 实现（无真实 LLM/MCP 调用），用于纯前端联调与 e2e。

## 16. ADR 候选（落地后补建）

进入 Phase 0 后第一批要写的 ADR（plan mode 下无法直接生成 `docs/ADR/` 文件）：

| 编号 | 决策 | 为什么值得 ADR |
|---|---|---|
| 001 | 桌面壳层选 **Tauri 2.x** 而非 Electron | v2 弃用 Tauri 的根因是当时紧耦合架构与 sidecar 集成不熟，**非 Tauri 本身缺陷**；Tauri 2 已具备 Electron 等价的 sidecar / 单实例锁 / Stronghold 凭证存储 / 自动更新等能力，包体积约为 Electron 的 1/8、内存占用更低、安全模型更严格；前端代码（React/Vite/Tailwind）与 Tauri 解耦，将来若极端情况需要切壳，迁移成本主要在 src-tauri/ 薄层。本决策曾在过程中一度切换至 Electron，后基于产品长期演进考虑回归 Tauri 2.x。 |
| 002 | 项目"指令"纯结构化入 DB，不再生成 YAML | 与 v2 大相径庭；影响数据流与导入导出能力 |
| 003 | 同时只能运行一个项目 | 限制 workflow_svc 调度器复杂度；后续放开成本高 |
| 004 | LLM 记录 = 1 provider+key 配多 model（嵌套表） | 影响 Agent FK、UI 选择器、迁移策略 |
| 005 | 用户 Tool 必须是 CrewAI BaseTool 子类 | 锁定与 CrewAI 版本绑定；放弃 MANIFEST 抽象 |
| 006 | 自动生成 Agent/Crew 入全局库带 `auto-generated` 徽章 | 影响团队页清单语义与未来"清理工具" |
| 007 | 项目根目录仅作为 Agent 默认产出路径，不限制读写 | 个人单机定位；未来对外开放需重做权限模型 |
| 008 | InteractionPort 通过 WS `prompt.request/response` 替代 input() | 关键架构模式；与 CrewAI 默认行为不同 |

## 17. MVP（v0.1.0）验收标准

衡量 v3 是否可发版的硬指标。每条不达标都不发布。

### 17.1 功能闭环
1. **建项目**：在主页"新建项目" → 与 LLM 对话 → AI 输出可编辑任务草案（含 `output_schema`）→ finalize → 项目卡出现，状态 `READY`。
2. **跑项目**：点开始 → 按 DAG 顺序+并发执行 → 每个 Task 输出经 schema 校验 → 全部完成 → final_qa Task 出 verdict → 项目状态根据 verdict 落到 completed/warnings/issues。
3. **暂停/恢复**：运行中点暂停 → 当前 Task 跑完后停止；强制中断生效；恢复后从暂停点继续。
4. **任务编辑**：项目暂停态下能在任务页增/删 Task、改依赖；rerun 单 Task 含级联选择。
5. **失败介入**：Task 失败 → 打开 Agent 对话 → 用户提示 → 重试成功后继续。
6. **MCP**：能录入 stdio + http 两种 MCP；状态条实时反映在线/离线；至少 2 个 MCP 工具通过手写包装 Tool 被 Agent 实际调用且参数 0 报错。
7. **配置**：LLM 录入 + 切换 model；双默认（立项/Agent）生效；系统权限 9 个开关切换实时生效。
8. **关闭与恢复**：项目运行中关窗 → 二次确认 → shutdown sequence 完成 → 重开应用提示恢复 → 选恢复后继续。

### 17.2 质量闸门
- **后端**：`pytest` 全绿；核心 `services/` 与 `domain/` 单元测试覆盖率 ≥ 70%。
- **前端**：`pnpm test` 全绿；关键组件（DAG、立项抽屉、IO 查看器）有快照测试。
- **E2E**：Playwright 跑通 §17.1 的 1+2+3+5 端到端冒烟。
- **IPC 集成测试套件**（§Phase 1）全绿。
- **Lint/Format**：ESLint / Ruff / cargo fmt 零 error。

### 17.3 性能预算
- **冷启动**：双击图标 → 主页可交互 < 5 秒（不含 MCP 实际握手时间）。
- **WS 心跳**：MCP 状态变化到前端 UI 反映 < 1 秒。
- **任务调度延迟**：上游 Task 完成到下游进入 running < 500ms（不含 LLM 调用）。
- **关闭**：用户点关闭到进程退出 < 15 秒（无运行项目时 < 3 秒）。
- **包体积**：安装包 ≤ 30MB（Tauri + PyInstaller 后端，未含 MCP 子进程）。

### 17.4 文档完整度
- `README.md`：用户视角的"5 分钟跑起来"。
- `docs/ARCHITECTURE.md`：本计划的精炼定稿版（无变更日志、无审议过程）。
- `docs/API.md`：FastAPI 自动导出的 OpenAPI JSON + WS 事件清单。
- `docs/USER_GUIDE.md`：首次使用 / LLM/MCP 配置 / 故障排查。
- `docs/ADR/`：ADR-001~008 至少落地。

### 17.5 可观测性
- **结构化日志**：每条日志带 `ts / level / source / project_id? / task_id? / event / message` 字段，JSON 行格式。
- **追踪 ID**：从 Tauri Command → REST → WS 事件全程贯穿同一 `request_id`。
- **诊断包**：一键导出 `data/logs/` + 配置（脱敏）+ 系统信息 + 最后 N 条 prompt_audit → `.zip`。

> **不在 MVP 范围**（明确推迟，避免功能蔓延）：
> - 自动更新（Phase 9 标可选）
> - 多项目并发运行
> - 系统权限的路径白名单与审批弹窗
> - RAG 文件索引
> - 国际化（中文优先，i18next 仅占位）
> - 任意第三方 LLM provider 插件（custom 类型已足够桥接）

## 18. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Tauri + Python sidecar 端口冲突 | 启动时探测 18321~18399 范围，握手后写入 Tauri-managed state，前端通过 `invoke('get_backend_port')` 拉取 |
| Tauri sidecar 二进制打包路径约定 | Tauri 要求 sidecar 二进制按 `{name}-{target-triple}.exe` 命名放进 `src-tauri/binaries/`；CI 脚本统一处理 |
| MCP stdio 进程僵死 | 每个 MCP 独立子进程 + 心跳超时强杀 + 用户可见状态 |
| LLM key 泄漏 | OS Keychain 优先；前端永远显示掩码；日志脱敏中间件 |
| CrewAI 库版本破坏 | 锁版本 + 在 `domain/` 包一层适配，CrewAI 升级只改适配层 |
| 状态机半完成态恢复歧义 | 引入 `epoch` 字段；每次启动只续跑同一 epoch 的运行 |
| Figma 设计稿落地误差 | Phase 1 后用 Figma MCP 拉每页截图比对；不强求像素一致 |
| **用户脚本 Tool 安全** | 强制走 `permission_svc` 白名单 + checksum + 首次加载弹窗确认；脚本进程隔离（subprocess + 资源限制） |
| **立项 LLM 输出格式不稳定** | 用 `function calling` / `JSON mode` 强制结构化；解析失败时回退为"让用户手填"模式 |
| **DAG 暂停语义复杂** | 用显式 task 状态机：pending/running/paused/done/failed；项目暂停只标 pending→paused，不影响 running |
| **关闭时 Agent 中途丢上下文** | shutdown 协议优先等当前任务自然结束（30s 超时）；超时后落盘 `last_state.json` 含 LLM 上下文 hash，下次提示用户"接续 / 重跑" |
| **MCP 子进程关闭后僵尸** | 关闭信号 → 等待 5s → SIGKILL；启动时扫描端口/PID 再次清理；记录到诊断包 |
| **`last_state.json` 损坏导致启动卡死** | 解析失败时直接重命名为 `last_state.broken.{ts}.json` 让用户上报，按"无快照"方式启动 |

---

## 关键文件路径速查

- 计划主文档：本文件
- v3 工作目录：`f:\ClaudeData\MyCrew_v3`（待初始化）
- v2 参考文档：`F:\ClaudeData\MyCrew_v2\docs\IMPLEMENTATION_GUIDE.md`
- 工作区规范：`F:\ClaudeData\CLAUDE.md`
- Figma 原型：`https://www.figma.com/design/1sr0yP4OSIpokBszeNkwYV/MyCrew`
  - 主页 node `5:25`、任务 `33:4683`、团队 `33:4685`、设置 `33:4684`
