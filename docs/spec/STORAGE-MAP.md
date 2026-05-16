# MyCrew 存储结构地图（Storage Map）

> **读者**：人类开发者 + 未来的 Core AI（Brain）
> **目的**：一份"什么数据在哪里、为什么在那里、谁可以改"的权威说明
> **更新策略**：新增表/字段/文件夹后必须同步更新本文档
> **最后更新**：2026-05-16（PM v4 schema + sub-step IO + WS session token + capture TTL）

本文档分四区：
1. [关系数据库（SQLite）](#1-关系数据库sqlite)
2. [文件系统](#2-文件系统)
3. [前端缓存](#3-前端缓存localstorage--react-query)
4. [运行时内存](#4-运行时内存)

文末有：
- [数据生命周期与清理策略](#5-数据生命周期与清理策略)
- [AI 取数速查表](#6-ai-取数速查表)

---

## 1. 关系数据库（SQLite）

**单点**：`data/db/mycrew.db`
**驱动**：aiosqlite（异步）+ Alembic（迁移）
**WAL 模式**：开启；连接时自动跑 `wal_checkpoint(TRUNCATE)`（防 WAL 累积）
**访问层**：`infra.repo.crud` 提供 `insert / get_by_id / get_all / update_by_id / delete_by_id / paginate`
**SQL 守卫（2026-05-16）**：表名 / 列名严格识别符；WHERE / ORDER BY 拒绝 `;` `--` `/*` `\x00`；`?` 数 = params 长度。违反抛 `SqlFragmentError`。

### 1.1 表分类总览

按用途分四组，每组的"谁会读 / 谁会写"标注清楚。

#### A. 项目工作流（最频繁变化的核心）
| 表 | 写者 | 读者 | 关键字段 |
|---|---|---|---|
| `projects` | project_svc, inception_svc, workflow_svc, watchdog_svc | 几乎所有 service | id, name, root_path, state, is_running, progress_pct, execution_kind, parent_project_id, iteration_index, template_id, favorited_at |
| `tasks` | workflow_svc, project_svc, create_workflow tool, planner_persist_svc | workflow_svc, crewai_runner, QA agent (via .mycrew/) | id, project_id, title, detail, agent_id, kind(regular\|final_qa\|setup), output_schema, status, deps, io_in_ref, io_out_ref, started_at, finished_at, last_activity_at, validation_errors, position_x/y, **last_error**, **last_error_kind** (0012), **performer_kind** / **performer_id** (0013 / PM v4) |

#### B. Agent / Crew / Tool（团队页 + 执行体系）
| 表 | 行数（PM v4 wipe 后） | 写者 | 读者 | 关键字段 |
|---|---|---|---|---|
| `agents` | 17 | seed_plan_maker, seed_planner_agents, seed_crews（**diff-then-update**，内容相同跳过 UPDATE）, agent_svc | crewai_runner, inception_svc, list_performers tool | id, role, goal, backstory, llm_id, tool_ids (JSON), is_auto_generated, max_retry, memory_enabled |
| `crews` | 8 | seed_crews, crew_svc | crewai_runner._run_crew, list_performers tool | id, name, process, agent_ids (JSON), is_auto_generated, **applicable_scenarios** (0013 / Phase 5 选 Crew 时读), **agent_sequence** (0013 / JSON head→executors→QA 链路 + step_instructions + progress_template) |
| `tools` | 79 | seed_builtin_tools | crewai_runner._load_builtin_tools, assign_agents | id, name, script_path, source, params_schema |

#### C. 立项会话（Plan Maker 对话历史）
| 表 | 行数 | 写者 | 读者 | 关键字段 |
|---|---|---|---|---|
| `inception_sessions` | 0 | inception_svc.create_session | inception_svc, frontend session 列表 | id, project_id, llm_id, mode, template_id, thinking_mode |
| `inception_messages` | 0 | inception_svc._stream_message_locked, _persist_initial_pick_message | inception_svc, frontend chat 渲染 | id, session_id, role (user/assistant), content, ts |

#### D. 配置 / 权限 / 审计
| 表 | 行数 | 写者 | 读者 | 关键字段 |
|---|---|---|---|---|
| `llm_providers` | 6 | llm_svc, 设置页 | llm_gateway, inception_svc | id, name, type, base_url, api_key_ref（**含敏感 key**） |
| `llm_models` | 15 | llm_svc | llm_gateway | id, provider_id, model_name, max_tokens, supports_thinking |
| `mcp_servers` | 7 | mcp_svc | mcp_pool, Plan Maker prompt | id, name, transport, command, args, url, env_ref, enabled, discovered_tools (JSON) |
| `permissions` | 9 | permission_svc | permission_guard | id, kind, pattern, allowed |
| `app_settings` | 2 | seed scripts | 多处 | key, value (含 `stall_timeout_minutes`, `plan_maker_prompt_version`) |
| `events` | 0 | **WsManager.broadcast** (自动) + audit middleware (自动) | LogDrawer, 未来 Brain | id, ts, event_type, actor, project_id, task_id, session_id, payload (JSON) |

#### E. 未启用（占位 / 未来）
| 表 | 用途 | 是否使用 |
|---|---|---|
| `logs` | 后端 structlog 落库（未接） | 否 |
| `prompt_audit` | 权限确认弹窗 audit（半接） | 否 |
| `chat_sessions` / `chat_messages` | 任务页与 Agent 对话（半接） | 否 |
| `experiences` | Agent 记忆 / RAG | 否 |

> 这 5 张未启用表保留 schema，做面向未来的接口预留；新功能想用直接接，**不要**清空或 drop。

### 1.2 迁移文件

`backend/migrations/versions/00XX_*.py` — Alembic 顺序：

| 版本 | 内容 |
|---|---|
| 0001 | baseline（projects/tasks/agents/...所有核心表） |
| 0002 | 加索引（tasks/inception_messages/llm_models/projects.state） |
| 0003 | experiences 表 |
| 0004 | projects.favorited_at / unfavorited_at |
| 0005 | tasks.position_x / position_y（画布拖拽） |
| 0007 | tasks.last_activity_at + stall_timeout_minutes（卡死检测） |
| 0008 | projects.parent_project_id / iteration_index / template_id；inception_sessions.template_id / mode |
| 0009 | tasks.validation_errors |
| 0010 | events 表 + ix_events_* 4 个索引 |
| 0011 | inception_sessions.last_activity_at + title |
| 0012 | tasks.last_error + last_error_kind |
| **0013** | **crews.applicable_scenarios + crews.agent_sequence；tasks.performer_kind + performer_id**（PM v4） |

> 注意：0006 跳号，与 plan 文件里的预留对齐，不影响生产。

---

## 2. 文件系统

**根目录**：`data/`（可改，由 `bootstrap/paths.py` 控制）

```
data/
├── db/
│   ├── mycrew.db                # SQLite 单文件，WAL 模式
│   └── mycrew.db.pre-v4.<ts>    # wipe_v4 留下的一次性备份（手动清理）
├── config/
│   ├── app.yaml                 # 应用启动配置（theme, default model 等）
│   └── unity_mcp.yaml           # Unity MCP 专用配置
├── cache/
│   └── mcp_health/              # MCP 健康探测短缓存
├── secrets/                     # 加密 keystore（占位；LLM key 当前仍存 DB，待 Stronghold 接入）
├── runtime/
│   ├── last_state.json          # 异常退出前的运行态快照
│   ├── session.token            # **WS session token**（每次后端启动重写）
│   └── _v4_reset_done.flag      # PM v4 wipe 已运行标志（删除可触发再 reset）
└── logs/                        # structlog 文件输出（如果配置启用）

output/                          # 任务输出根目录（非 data/ 下）
├── <project_id>/
│   └── <task_id>/
│       ├── in.json / in.md      # 任务输入（结构化 + 人类可读）
│       ├── out.json / out.md    # 任务输出（QA step 或单 agent 任务）
│       └── sub/                 # **PM v4** Crew 任务的 sub-step IO
│           ├── 0_head_in.json
│           ├── 0_head_out.json
│           ├── 0_head_out.md
│           ├── 1_executor_in.json
│           ├── 1_executor_out.json
│           ├── 1_executor_out.md
│           └── N_qa_*.json/.md
└── …

<用户项目 root_path>/.mycrew/    # Plan Maker 写入项目工程内
├── blueprint.json               # 项目元数据 + 完整任务图
├── architecture.md              # 人类可读架构说明
├── tasks/task_NN_*.md           # 每个任务的 detail + 验收要点
├── _planner_trace.json          # PM v3/v4 5-phase 调试日志（每个项目一份）
└── iter-NNN/                    # 迭代轮次独立命名空间
    ├── blueprint.json
    └── tasks/...
```

### 2.1 谁写谁读
| 路径 | 写者 | 读者 |
|---|---|---|
| `data/db/mycrew.db` | 所有 service | 所有 service |
| `data/config/app.yaml` | 用户手工 / 设置页 | bootstrap |
| `data/config/unity_mcp.yaml` | 用户手工 | mcp_svc |
| `data/runtime/session.token` | bootstrap/app.lifespan（每次启动） | api/routes_auth + WS handshake |
| `data/runtime/_v4_reset_done.flag` | bootstrap/wipe_v4.run_v4_reset_once | bootstrap/wipe_v4 自身（决定跳过/执行） |
| `output/<pid>/<tid>/out.json` | workflow_svc._save_task_output | IoViewerDrawer (frontend), QA agent |
| `output/<pid>/<tid>/sub/<i>_*_*.json` | workflow_svc._save_sub_step_io | sub_io endpoint + task_guidance (step-scoped) |
| `<root>/.mycrew/blueprint.json` | planner_persist_svc.save_draft_as_project / write_blueprint tool | QA agent (read_file_local) |
| `<root>/.mycrew/architecture.md` | 同上 | 人类开发者 |
| `<root>/.mycrew/tasks/task_NN.md` | 同上 | QA agent |
| `<root>/.mycrew/_planner_trace.json` | planner_persist_svc.save_draft_as_project | 后人 debug |

### 2.2 清理
- `output/` 在 `scripts/cleanup_residuals.py` 中跟随项目删除一起清
- `<root>/.mycrew/` **不在自动清理范围**（属于用户工程内容，git 管）

---

## 3. 前端缓存（localStorage + react-query）

### 3.1 localStorage —— `usePrefsStore` (`mycrew-prefs` key)
zustand persist。**仅前端可见**，后端读不到，AI Brain 也读不到（除非同步到 DB，目前未做）。

| 字段 | 含义 |
|---|---|
| inceptionLlm / inceptionModel / inceptionThinking | Plan Maker 工具栏默认 LLM |
| logDrawerExpanded / logDrawerActiveTab | 日志抽屉展开状态 |
| teamActiveTab / settingsActiveTab | 团队页 / 设置页当前 tab |
| lastProjectId | 最近打开的项目（用于卡片"已载入"光晕 + /tasks 直接重定向） |
| ioViewerWidth | IO 查看器宽度（默认 380，clamp 280–1200） |

### 3.2 react-query 缓存
| queryKey | 内容 | invalidation |
|---|---|---|
| `["projects", page]` | 项目列表 + 进度 | 任何项目 CRUD |
| `["project", id]` | 单项目详情 + 任务 | 任务/项目状态变化 |
| `["agents"]` | 全部 agent 列表 | agent CRUD |
| `["agents", "assignable"]` | 排除 auto_generated 的 agent | 同上 |
| `["templates"]` | Unity 模板列表 | 静态 5min staleTime |
| `["mcp_servers"]` | MCP 列表 | MCP CRUD |
| `["llm_providers"]` | LLM 列表 | LLM CRUD |
| `["inception", sessionId]` | 单 session 消息 | 发消息 / 选模板 |
| `["events", filters]` | 事件查询结果 | 手动 invalidate |

---

## 4. 运行时内存

| 实例 | 类型 | 在哪里 | 持久化？ | 清理 |
|---|---|---|---|---|
| `workflow_svc._active` | dict[project_id → HarnessStateMachine] | services/workflow_svc.py | **否** — 重启即丢，watchdog reconcile 兜底 | `_cleanup_project` |
| `workflow_svc._runners` | dict[project_id → TaskRunner] | 同上 | 否 | 同上 |
| `workflow_svc._outputs` | dict[project_id → dict[task_id → output]] | 同上 | 否，但 `tasks.io_out_ref` 有 | 同上 |
| `workflow_svc._run_tasks` | dict[key → asyncio.Task] | 同上 | 否 | 同上 |
| **`workflow_svc._project_locks`** | dict[project_id → asyncio.Lock] | 同上（2026-05-16 新增） | 否 | `_cleanup_project` |
| `_output_capture._outputs` | dict[task_id → (payload, ts)] | src/tools/builtin/local/_output_capture.py | 否 | Pop 时清；摊销 `_evict_expired`（**TTL = 1h**） |
| `_output_capture._planner_outputs` | dict[(session_id, phase) → (payload, ts)] | 同上 | 否 | `clear_planner_session` + 摊销 `_evict_expired`（**TTL = 4h**） |
| **`planner_cache_svc._sessions`** | dict[session_id → dict] | services/planner_cache_svc.py | 否（"save to persist" 语义） | `clear(session_id)` 显式 |
| `mcp_pool._processes` | dict[server_id → subprocess] | infra/mcp/pool.py | 否，进程级 | 关闭 / `disconnect_server` |
| `manager._connections` | list[WebSocket] | api/ws.py | 否 | 客户端断开时 |
| **`api/ws._SESSION_TOKEN`** | str（模块级单例） | api/ws.py | 否 | 仅启动时设置一次 |
| `inception_svc._session_locks` | defaultdict[session_id → asyncio.Lock] | services/inception_svc.py | 否 | 进程退出 |
| **request_id contextvar** | ContextVar[str] | infra/request_context.py + bootstrap/app.py 中间件 | 否（请求结束 unbind） | `try/finally` 中 unbind |

> 运行时内存挂掉怎么办：
> - workflow_svc 重启后 `reconcile_all_orphans_on_startup` 把残留 `is_running=1` 项目按 task 终态推断成 STALLED / COMPLETED_WITH_ISSUES / PAUSED
> - 然后 watchdog 每 60s 兜一次

---

## 5. 数据生命周期与清理策略

| 数据 | 保留时长 | 清理路径 |
|---|---|---|
| `events` 表 | 全局 30 天 / 单项目 ≤ 10000 行 | `services.events_svc.run_event_janitor`（6h 一次） |
| `output/<pid>/` 主目录 | 跟随项目删除 | `scripts/cleanup_residuals.py` 手工 / 未来加 UI |
| `output/<pid>/<tid>/sub/` | 跟随任务删除 | 同上 |
| `_output_capture._outputs`（任务级） | TTL 1 小时（摊销） | `_evict_expired` 摊销清理 |
| `_output_capture._planner_outputs`（phase 级） | TTL 4 小时（摊销） | `_evict_expired` + `clear_planner_session` |
| 任务 `last_activity_at` | 无限（小） | 不清理 |
| `inception_*` 表 | 无限 | 删项目时 cascade |
| MCP `discovered_tools` JSON | 直到 MCP 配置改动 | `mcp_svc.refresh_tools` |
| WS 连接 | 仅会话期 | 断线即清 |
| `data/runtime/session.token` | 直到下次后端启动（每次重写） | 每次 lifespan 覆盖 |
| `data/db/mycrew.db.pre-v4.<ts>` | 永久（除非手动删） | **无自动清理 — 占空间需关注** |
| localStorage prefs | 永久（除非用户清浏览器） | 不清理 |
| react-query 缓存 | tabClose / 主动 invalidate | 默认 5min staleTime |

### 5.1 一键残留清理
```bash
cd backend
python scripts/cleanup_residuals.py
```
保留：llm_providers, llm_models, mcp_servers, tools, agents (非 auto_generated), permissions, app_settings
清空：projects, tasks, output/proj_*, inception_sessions (含孤儿), inception_messages, auto_generated crews

---

## 6. AI 取数速查表

> 给未来 Core AI（Brain）的"问诊"线索图。

**"项目现状"**
```sql
SELECT id, name, state, is_running, progress_pct, root_path, template_id, iteration_index
FROM projects ORDER BY created_at DESC;
```

**"某项目所有任务的当前状态"**
```sql
SELECT t.id, t.title, t.status, t.kind, a.role AS agent_role,
       t.started_at, t.finished_at, t.last_activity_at, t.validation_errors
FROM tasks t LEFT JOIN agents a ON t.agent_id = a.id
WHERE t.project_id = ? ORDER BY t.rowid;
```

**"某任务的真实输出"**
- 结构化：`output/<project_id>/<task_id>/out.json`
- 原始：`output/<project_id>/<task_id>/out.md`
- DB 字段：`tasks.io_out_ref`（仅 path 指针）

**"最近 N 个事件"** —— Brain 启动第一查询
```sql
SELECT ts, event_type, actor, project_id, payload
FROM events
ORDER BY ts DESC LIMIT 200;
```
或 HTTP：`GET /api/v1/events?limit=200`

**"某项目的事件历史"**
```sql
SELECT ts, event_type, payload FROM events
WHERE project_id = ? ORDER BY ts DESC LIMIT 500;
```
或 HTTP：`GET /api/v1/events?project_id=proj_xxx`

**"Plan Maker 对话历史"**
```sql
SELECT m.role, m.content, m.ts
FROM inception_messages m
JOIN inception_sessions s ON m.session_id = s.id
WHERE s.project_id = ? ORDER BY m.ts;
```

**"项目设计意图"**
- `<root>/.mycrew/architecture.md` — 人类语言
- `<root>/.mycrew/blueprint.json` — 机器可读任务图 + acceptance_notes

**"用户的近期操作"**（API mutation 审计）
```sql
SELECT ts, payload FROM events
WHERE event_type = 'api.mutation'
ORDER BY ts DESC LIMIT 100;
```

**"Plan Maker 现行规则"** —— 不要从代码反推，看
- `backend/bootstrap/seed_plan_maker.py` — backstory 模板源头
- `backend/data/unity_templates.py` — 5 个模板的完整 skeleton
- `backend/src/tools/builtin/local/create_workflow.py` — `QA_TASK_DETAIL` 强制注入

**"系统能调用哪些工具"**
```sql
SELECT name, script_path FROM tools ORDER BY name;
```
对照 `backend/services/crewai_runner.py` 的 `_load_builtin_tools` 注册表看哪些是 ctx-bound vs 静态。

---

## 7. 变更须知（给修改本文档的人）

每次以下操作必须更新本文档：
- 新增 / 删除 / 改名 DB 表
- 新增 / 删除 / 改名 表字段（特别是含敏感数据的）
- 改变 `data/` 文件夹结构
- 改变 `output/` / `.mycrew/` 落盘策略
- 改变保留时长 / 清理触发器
- 新增任何"运行时-only 状态"
- 新增任何 localStorage 字段

更新流程：直接编辑本文件，commit message 前缀 `docs(storage):`。
