# MyCrew v3 — 主题索引（反向查找表）

> **干什么用**：按主题 / 问题 / 动词反查"该看哪份文档、改哪份代码"。
> **跟 `docs/README.md` 的区别**：README 是按目录的**导航**（spec / iterations / roadmap），本文是按**关键词的查找表**。两份互补。
> **最后更新**：2026-05-16

---

## 第一节 · 速查（最常用的 10 个入口）

| 我想… | 去这里 |
|---|---|
| 看当前架构总览 | [`spec/ARCHITECTURE.md`](./spec/ARCHITECTURE.md) §1-§4 |
| 看 REST / WS API 契约 | [`spec/API.md`](./spec/API.md) |
| 看 DB 表 + 文件落盘 | [`spec/STORAGE-MAP.md`](./spec/STORAGE-MAP.md) |
| 看 PM v4 怎么跑 Crew 任务 | [`spec/ARCHITECTURE.md`](./spec/ARCHITECTURE.md) §11 + [iterations/2026-05-16/pm-v4-plan.md](./iterations/2026-05-16/pm-v4-plan.md) |
| 看上次的安全审查 + Top 5 风险 | [`iterations/2026-05-16/architecture-audit.md`](./iterations/2026-05-16/architecture-audit.md) |
| 看本轮落地了什么修复 | [`iterations/2026-05-16/audit-followup-2026-05-16.md`](./iterations/2026-05-16/audit-followup-2026-05-16.md) |
| 看下一步该做什么（按触发条件） | [`roadmap/`](./roadmap/) 四个 backlog 文档 |
| 看下次审核的开局地图 | [`roadmap/next-audit-prep.md`](./roadmap/next-audit-prep.md) |
| 看架构决策的来龙去脉 | [`ADR/`](./ADR/) 8 条 |
| 故障排查（DB locked / WS 连不上 / …） | 本文 [§5 故障排查](#5-故障排查-按症状查) |

---

## 第二节 · 按主题查找

### 2.1 后端架构

| 主题 | 权威文档 | 代码位置 |
|---|---|---|
| 分层架构（domain / infra / services / api / agents） | [spec/ARCHITECTURE.md §1-§2](./spec/ARCHITECTURE.md) | `backend/` 各目录 |
| 启动 lifespan 步骤 | spec/ARCHITECTURE.md §8.2 | `backend/bootstrap/app.py:lifespan` |
| 事件总线 | spec/ARCHITECTURE.md §3.2 + ADR-008 | `backend/infra/event_bus/in_memory_bus.py` |
| InteractionPort（替代 input()） | spec/ARCHITECTURE.md §3.3 + ADR-008 | `backend/infra/interaction/ws_interaction.py` |
| 主事件循环引用（worker thread hop） | — | `backend/infra/runtime.py` |
| Domain Events 类型 | — | `backend/domain/events.py` |
| 状态机（Harness / Task） | spec/ARCHITECTURE.md §4.1 | `backend/domain/harness/state_machine.py` |
| DAG 校验 | — | `backend/domain/qa/dag_validator.py` |

### 2.2 PM v3 / v4 规划器

| 主题 | 权威文档 | 代码位置 |
|---|---|---|
| PM v3 5-phase 设计原由 | [iterations/2026-05-15/pm-v3-plan.md](./iterations/2026-05-15/pm-v3-plan.md) + grill | — |
| PM v4 Crew-Native 设计原由 + 13 轮决策 | [iterations/2026-05-16/pm-v4-plan.md](./iterations/2026-05-16/pm-v4-plan.md) | — |
| PM v4 落地报告（A-G 7 stage） | git log 区间 `8a97971..80f8555` | — |
| 5-phase 编排主流程 | spec/ARCHITECTURE.md §11.2-11.3 | `backend/agents/sub_agents/_planner_orchestrator.py` |
| Pydantic 渐进式模型链 | — | `backend/agents/sub_agents/_planner_models.py` |
| 5 个 submit_xxx 工具 | — | `backend/agents/sub_agents/_planner_tools.py` |
| Phase 1-5 prompts | — | `backend/agents/sub_agents/_planner_prompts.py` |
| `list_performers` 工具（Phase 5） | spec/ARCHITECTURE.md §11.2 + spec/API.md PM | `backend/agents/sub_agents/_list_performers_tool.py` |
| `_validate_assignments` 二次校验 | iterations/2026-05-16/audit-followup §D | `backend/agents/sub_agents/_planner_orchestrator.py` |
| 内存缓存（in-memory，"save to persist"） | spec/STORAGE-MAP.md §4 | `backend/services/planner_cache_svc.py` |
| 草稿落盘（cache → DB + .mycrew/） | — | `backend/services/planner_persist_svc.py` |
| 8 个预设 Crew 定义 | spec/ARCHITECTURE.md §11.2 + iterations/2026-05-16/pm-v4-plan.md | `backend/bootstrap/seed_crews.py` |
| Crew step IO 落盘 | spec/STORAGE-MAP.md §2 | `backend/services/workflow_svc.py:_save_sub_step_io` |
| `task.sub_step` WS 事件 | spec/API.md WS Events | `backend/services/workflow_svc.py:_broadcast_sub_step` |

### 2.3 工作流执行

| 主题 | 权威文档 | 代码位置 |
|---|---|---|
| `_run_agent` / `_run_crew` 路由 | spec/ARCHITECTURE.md §11.3 | `backend/services/workflow_svc.py` |
| 单 agent CrewAI 执行 | — | `backend/services/crewai_runner.py:run_task_with_crewai` |
| Crew 单步 CrewAI 执行 | — | `backend/services/crewai_runner.py:run_crew_step_with_crewai` |
| `emit_output` 工具（含 plural file_paths） | iterations/2026-05-16/audit-followup §A | `backend/src/tools/builtin/local/emit_output.py` |
| 任务错误分类（quota/auth/mcp/...） | spec/ARCHITECTURE.md §12 | `backend/services/workflow_svc.py:_classify_task_error` |
| Watchdog（卡死 + orphan reconcile） | spec/ARCHITECTURE.md §12 + §10 | `backend/services/watchdog_svc.py` |
| LLM 90s 硬超时 | spec/ARCHITECTURE.md §12 | `backend/infra/llm/gateway.py:LLM_CALL_TIMEOUT_SECONDS` |

### 2.4 工具系统

| 主题 | 权威文档 | 代码位置 |
|---|---|---|
| Tool 扩展协议（BaseTool 子类） | spec/ARCHITECTURE.md §7.5 + ADR-005 | `src/tools/builtin/` |
| MCP 工具包装层 | spec/ARCHITECTURE.md §7.6 | `backend/src/tools/builtin/mcp_<server>/` |
| Builtin tool 注册表 | — | `backend/bootstrap/seed_builtin_tools.py` |
| crewai_runner tool registry | — | `backend/services/crewai_runner.py:_load_builtin_tools` |
| GuardedLocalTool / GuardedMCPTool 基类 | spec/ARCHITECTURE.md §12 | `backend/src/tools/builtin/_base.py` |
| 权限矩阵 + 启发式工具名匹配 | spec/ARCHITECTURE.md §2.2 | `backend/services/permission_guard.py` |
| `synth_8bit_sfx`（PM v4 Audio Crew） | iterations/2026-05-16/audit-followup §A | `backend/src/tools/builtin/local/synth_8bit_sfx.py` |
| `emit_output` 输出捕获模块 | — | `backend/src/tools/builtin/local/_output_capture.py` |
| Unity MCP 34 工具 | — | `backend/src/tools/builtin/unity/` |
| Blender MCP | — | `backend/src/tools/builtin/mcp_blender/` |
| ComfyUI MCP | — | `backend/src/tools/builtin/mcp_comfyui/` |
| Figma MCP | — | `backend/src/tools/builtin/mcp_figma/` |
| Tavily MCP | — | `backend/src/tools/builtin/mcp_tavily/` |
| Git MCP（factory-bound） | — | `backend/src/tools/builtin/mcp_git/` |
| Workspace tools（write_file / mkdir） | spec/ARCHITECTURE.md §12 | `backend/src/tools/builtin/local/workspace.py` |

### 2.5 数据层

| 主题 | 权威文档 | 代码位置 |
|---|---|---|
| 所有表 + 字段 | spec/STORAGE-MAP.md §1.1 | `backend/migrations/versions/` |
| 迁移历史（0001-0013） | spec/STORAGE-MAP.md §1.2 | 同上 |
| CRUD 模块 + SQL 守卫 | spec/ARCHITECTURE.md §12 | `backend/infra/repo/crud.py` |
| SQLite + WAL + 启动 TRUNCATE | spec/STORAGE-MAP.md §1 | `backend/infra/repo/sqlite_repo.py` |
| 文件落盘约定 | spec/STORAGE-MAP.md §2 | — |
| 运行时内存清单 | spec/STORAGE-MAP.md §4 | — |
| 数据生命周期 / TTL / 备份 | spec/STORAGE-MAP.md §5 | — |
| 一次性 PM v4 wipe | — | `backend/bootstrap/wipe_v4.py` |
| 一键残留清理 | spec/STORAGE-MAP.md §5.1 | `backend/scripts/cleanup_residuals.py` |
| DB lock 恢复脚本 | — | `scripts/recover-db-lock.ps1` |

### 2.6 安全 / 加固模块（2026-05-16 Phase 1/2 落地）

| 主题 | 权威文档 | 代码位置 |
|---|---|---|
| WS session token 鉴权 | spec/ARCHITECTURE.md §12 + spec/API.md "Auth (WS Token)" | `backend/api/ws.py` + `backend/api/routes_auth.py` + `backend/bootstrap/app.py:lifespan` |
| WorkflowService per-project asyncio.Lock | spec/ARCHITECTURE.md §12 | `backend/services/workflow_svc.py:_project_locks` |
| `create_project_with_tasks` 补偿事务 | iterations/2026-05-16/audit-followup §P1.3 | `backend/services/project_svc.py` |
| SQL fragment 守卫 | spec/ARCHITECTURE.md §12 | `backend/infra/repo/crud.py` |
| request_id middleware + structlog binding | spec/ARCHITECTURE.md §12 | `backend/bootstrap/app.py:_request_id_middleware` + `backend/infra/request_context.py` |
| audit middleware（POST/PUT/DELETE 落 events） | spec/ARCHITECTURE.md §3.1 | `backend/bootstrap/app.py:_audit_middleware` |
| `_output_capture` TTL 摊销清理 | spec/STORAGE-MAP.md §4 + §5 | `backend/src/tools/builtin/local/_output_capture.py:_evict_expired` |
| Tauri CSP / 能力 allowlist（**未做**） | [roadmap/phase3-deferred-to-packaging.md §D2](./roadmap/phase3-deferred-to-packaging.md) | `src-tauri/tauri.conf.json:csp` |
| LLM key 加密（**未做**） | [roadmap/phase3-deferred-to-packaging.md §D1](./roadmap/phase3-deferred-to-packaging.md) | `backend/services/llm_svc.py:174` |

### 2.7 前端

| 主题 | 权威文档 | 代码位置 |
|---|---|---|
| 4 个页面 + 抽屉 | spec/ARCHITECTURE.md §2.1 | `frontend/src/pages/` |
| 设计系统（DEFAULT 默认风格） | [spec/DESIGN-SYSTEM.md](./spec/DESIGN-SYSTEM.md) | `frontend/src/styles/globals.css` |
| Canvas + ReactFlow + 自定义 node | spec/ARCHITECTURE.md §11.4 | `frontend/src/components/task/Canvas*.tsx` |
| Crew node + 展开 / 折叠 + 下游平移 | spec/ARCHITECTURE.md §11.4 | `frontend/src/components/task/CanvasCrewNode.tsx` |
| Sub-card + Q11 action gating | spec/ARCHITECTURE.md §11.4 | `frontend/src/components/task/SubAgentCard.tsx` |
| 任务卡片 + 错误黄标 | — | `frontend/src/components/task/TaskNode.tsx` |
| IO viewer drawer（任务 + Crew step） | spec/API.md Workflow | `frontend/src/components/task/IoViewerDrawer.tsx` |
| Agent chat drawer（含 step scope） | — | `frontend/src/components/task/AgentChatDrawer.tsx` |
| Plan Maker inception drawer | — | `frontend/src/components/inception/InceptionDrawer.tsx` |
| PMDebugLog（5-phase 进度） | — | `frontend/src/components/inception/PMDebugLog.tsx` |
| Template 选择 / 路径选择 panel | — | `frontend/src/components/inception/{ChoicePanel,PathInputPanel}.tsx` |
| WS 客户端（含 token + 重连） | spec/API.md "Auth (WS Token)" | `frontend/src/net/ws.ts` |
| HTTP 客户端（含 X-Request-ID） | spec/API.md 总览 | `frontend/src/net/api.ts` |
| 聊天队列 hook（单飞 + 思考中） | — | `frontend/src/hooks/useChatQueue.ts` |
| WS 事件订阅 hook（稳定 wrapper） | — | `frontend/src/hooks/useEvent.ts` |
| 项目卡 3 模式 path picker | — | `frontend/src/components/home/ProjectCard.tsx` |

### 2.8 配置 / 设置

| 主题 | 权威文档 | 代码位置 |
|---|---|---|
| 启动配置（theme / language / 窗口） | spec/STORAGE-MAP.md §2 | `data/config/app.yaml` |
| ENV 变量（MYCREW_DEV / PORT / LOG_LEVEL） | — | `backend/bootstrap/paths.py` |
| LLM provider + model | spec/API.md "LLM" + ADR-004 | `backend/services/llm_svc.py` |
| MCP server 配置 | spec/API.md "MCP" | `backend/services/mcp_svc.py` |
| 权限矩阵 9 个 kind | spec/ARCHITECTURE.md §2.2 + 12 | `backend/services/permission_svc.py` |
| 模板（5 个 Unity 模板） | spec/API.md "Templates" | `backend/data/unity_templates.py` |

---

## 第三节 · "我想做 X" — 动词查找

### 3.1 加东西

| 我想加 | 步骤 |
|---|---|
| **一个新 builtin tool** | 1. 写 `BaseTool` 子类到 `backend/src/tools/builtin/<group>/` 2. 注册到 `backend/services/crewai_runner.py:_load_builtin_tools` 3. 加到 `backend/bootstrap/seed_builtin_tools.py:BUILTIN_TOOLS` 4. 重启 backend |
| **一个新 MCP server** | 1. UI 设置页加 server 行（或直接写 DB `mcp_servers`） 2. 为每个要暴露的 tool 写 wrapper（参考 `mcp_blender/`） 3. 走 builtin tool 注册流程（同上） — 见 spec/ARCHITECTURE.md §7.6 |
| **一个新 Crew** | 1. 在 `backend/bootstrap/seed_crews.py:SEED_CREWS` 加一项（含 applicable_scenarios + agent_sequence） 2. 重启 backend 自动 seed 3. Phase 5 LLM 调 `list_performers` 时就会看到它 |
| **一个新 standalone agent** | 1. 在 `seed_crews.py:SEED_AGENTS` 加（注意 role 要在 `_list_performers_tool._STANDALONE_AGENT_ROLES` 里才会暴露给 Phase 5） |
| **一个新 migration** | 1. 新建 `backend/migrations/versions/00XX_<name>.py`（参考 0013） 2. 重启 backend 自动应用 3. 更新 [spec/STORAGE-MAP.md §1.2](./spec/STORAGE-MAP.md) |
| **一个新 REST 端点** | 1. 加到现有 `backend/api/routes_*.py` 或新建 2. 如果新建：在 `backend/bootstrap/app.py:create_app` include_router 3. 更新 [spec/API.md](./spec/API.md) |
| **一个新 WS 事件** | 1. 后端 `manager.broadcast(event_type, payload)`（任何 service 都可调） 2. 前端 `useEvent(event_type, handler)` 订阅 3. 更新 spec/API.md "WS Events" |
| **一个新 ADR** | 1. 在 `docs/ADR/` 新建 `00<N>-<title>.md`（参考现有命名） 2. 在 spec/ARCHITECTURE.md 附录 A 加索引行 |
| **一个新 iteration log** | 1. 在 `docs/iterations/<YYYY-MM-DD>/` 建目录 2. 写 plan / followup / 其他 |
| **未来规划文档** | 1. 在 `docs/roadmap/<feature-name>.md` 写，**必须**标触发条件 + 工作量 |

### 3.2 改东西

| 我想改 | 改哪儿 |
|---|---|
| **PM v3/v4 5-phase prompt** | `backend/agents/sub_agents/_planner_prompts.py` |
| **Phase 5 performer 池过滤规则**（哪些 agent 可被 Phase 5 选） | `backend/agents/sub_agents/_list_performers_tool.py:_STANDALONE_AGENT_ROLES` |
| **Crew 步骤的 step_instructions** | `backend/bootstrap/seed_crews.py:SEED_CREWS` |
| **任务错误分类规则** | `backend/services/workflow_svc.py:_ERROR_KIND_PATTERNS` |
| **错误黄标 tooltip 文案** | `frontend/src/components/task/TaskNode.tsx:KIND_HEADLINES` |
| **任务卡片尺寸 / 画布间距** | `frontend/src/components/task/TaskNode.tsx`（width） + `CanvasBlueprint.tsx`（COL_W / ROW_H） |
| **诊断聊天助手的 LLM** | 当前钉死在 `deepseek-flash`，见 `backend/agents/task_guidance.py` |
| **项目初始化助手的 LLM** | 同上钉死，见 `backend/bootstrap/seed_planner_agents.py` |
| **LLM 硬超时** | `backend/infra/llm/gateway.py:LLM_CALL_TIMEOUT_SECONDS` |
| **`_output_capture` TTL** | `backend/src/tools/builtin/local/_output_capture.py:_TASK_OUTPUT_TTL_S` / `_PLANNER_OUTPUT_TTL_S` |
| **events 表保留期** | `backend/services/events_svc.py:run_event_janitor` |
| **审计中间件忽略路径** | `backend/bootstrap/app.py:_AUDIT_SKIP_PREFIXES` |
| **CORS 允许的 origin** | `backend/bootstrap/app.py:create_app` 中的 CORSMiddleware |

### 3.3 调试 / 看运行时状态

| 我想看 | 方法 |
|---|---|
| **当前所有运行中项目** | `GET /api/v1/workflow/active` 或后端 log 里 `workflow.started` |
| **某项目所有任务状态** | `GET /api/v1/projects/<id>`（含 tasks 数组） |
| **某任务的真实输出** | `output/<pid>/<tid>/out.json` 或 UI 任务卡片 → IO 查看 |
| **Crew 任务的单步 IO** | `output/<pid>/<tid>/sub/<i>_*_*.json` 或 UI 子卡片 → IO 查看 |
| **某次审计事件** | `GET /api/v1/events?project_id=<pid>` 或 SQL `SELECT * FROM events ORDER BY ts DESC` |
| **某 task_id 的所有事件** | SQL `SELECT * FROM events WHERE task_id = ?` |
| **structlog 输出** | 后端 stdout（开发模式是 console，生产是 JSON） |
| **WS 连接状态** | 浏览器 DevTools Network → WS tab |
| **DB schema 当前长啥样** | SQLite CLI 或 `PRAGMA table_info(<table>)` |
| **PM v3/v4 session 当前进度** | `GET /api/v1/pm/sessions/<sid>/state` 或前端 PMDebugLog |
| **某请求的完整调用链** | 看响应头 `X-Request-ID`，到后端 log 里 grep |

---

## 第四节 · 按代码位置反查（"这文件做啥的"）

> 仅列**高价值文件**。完整模块清单见 [spec/ARCHITECTURE.md §2.2](./spec/ARCHITECTURE.md)。

### 后端关键文件

| 文件 | 一句话总结 |
|---|---|
| `backend/bootstrap/app.py` | FastAPI app 装配 + lifespan 7 步启动 + 3 层 middleware（CORS / audit / request_id） |
| `backend/bootstrap/main.py` | uvicorn 入口 + 端口发现 + structlog 配置 |
| `backend/bootstrap/wipe_v4.py` | 一次性 PM v4 reset（已运行；不会再触发） |
| `backend/bootstrap/seed_crews.py` | 8 Crew + 14 agent 的幂等 seed（diff-then-update） |
| `backend/services/workflow_svc.py` | 任务调度核心：start/pause/resume/abort/retry + per-project Lock + `_run_crew` |
| `backend/services/crewai_runner.py` | CrewAI 桥（单 agent + Crew step）+ tool registry |
| `backend/services/project_svc.py` | 项目 CRUD + 补偿事务 |
| `backend/services/planner_orchestrator.py` *(实际在 agents/sub_agents/)* | PM v3/v4 5-phase 编排 |
| `backend/services/events_svc.py` | 事件持久化 + 6h janitor |
| `backend/services/watchdog_svc.py` | 卡死探测 + orphan 启动 reconcile |
| `backend/infra/repo/crud.py` | 所有 SQL 入口；**含 fragment 守卫** |
| `backend/infra/llm/gateway.py` | LLM provider 抽象 + 90s 硬超时 |
| `backend/infra/mcp/pool.py` | MCP 连接池 + 心跳 + 指数退避重连 |
| `backend/api/ws.py` | WS Hub + session token 校验 |
| `backend/api/routes_auth.py` | `GET /auth/ws_token` 端点 |
| `backend/api/routes_workflow.py` | 工作流 + sub_io + guidance 端点 |
| `backend/agents/sub_agents/_planner_orchestrator.py` | 5-phase 主循环 |
| `backend/agents/sub_agents/_planner_models.py` | Pydantic 模型链 |
| `backend/agents/sub_agents/_list_performers_tool.py` | Phase 5 工具 |
| `backend/agents/task_guidance.py` | 诊断聊天（含 step 级 scope） |

### 前端关键文件

| 文件 | 一句话总结 |
|---|---|
| `frontend/src/pages/TaskPage.tsx` | 任务页主组件 + drawer 状态 + sub-step action 路由 |
| `frontend/src/components/task/CanvasBlueprint.tsx` | DAG 画布 + nodeTypes 路由（task / crew） + 下游平移 |
| `frontend/src/components/task/CanvasCrewNode.tsx` | Crew 任务节点 + 折叠/展开 + WS sub_step 订阅 |
| `frontend/src/components/task/SubAgentCard.tsx` | Crew 子卡片 + Q11 action gating |
| `frontend/src/components/task/IoViewerDrawer.tsx` | IO 查看抽屉（含 sub-step 模式） |
| `frontend/src/components/task/AgentChatDrawer.tsx` | 诊断对话（含 step scope） |
| `frontend/src/components/inception/InceptionDrawer.tsx` | Plan Maker 半页抽屉（含模板 / 路径选择 / 历史） |
| `frontend/src/components/inception/PMDebugLog.tsx` | PM 5-phase 进度日志渲染 |
| `frontend/src/net/ws.ts` | WS 客户端（含 token 获取 + 4401 重试 + ghost cleanup） |
| `frontend/src/net/api.ts` | HTTP 客户端 + 超时 + AbortSignal 合成 |

### 配置 / 脚本

| 文件 | 一句话总结 |
|---|---|
| `backend/pyproject.toml` | 后端依赖 + pytest 配置 |
| `backend/alembic.ini` | Alembic 迁移配置 |
| `backend/migrations/versions/0013_crew_pool.py` | 最新 migration（PM v4 schema） |
| `frontend/package.json` | 前端依赖 |
| `frontend/vite.config.ts` | Vite 配置 |
| `scripts/recover-db-lock.ps1` | DB lock 恢复脚本（kill 残留进程 + WAL TRUNCATE） |
| `tauri.conf.json` *(在 src-tauri/)* | Tauri 配置（CSP 当前 null，待打包前启用） |

---

## 第五节 · 故障排查（按症状查）

| 症状 | 原因 + 修法 |
|---|---|
| 后端启动卡在 `db.connected` 后没动 | DB 被另一个 python 进程锁住，且 WAL 文件累积过大。跑 `scripts/recover-db-lock.ps1` 清残留进程 + WAL TRUNCATE。详见 git commit `26d7530` |
| 前端 "后端未连接或不可达" | 后端没起 / 端口不对 / 多个 backend 同时跑。检查 PowerShell 后端窗口是否有 error；用 `tasklist | grep python` 看进程 |
| WS 一直 disconnect → connect 循环 | session token 不匹配（后端重启就会换 token）。前端会自动 refetch `/auth/ws_token` + 重连。看后端 log 是否有 `ws.auth_rejected` |
| 任务卡片确认按钮点了没反应 | 后端创建失败但前端没显示错误（已修：commit `5788bbc` 加了红色错误条 + "处理中…" 状态）。若仍不响应，刷新浏览器（Ctrl+Shift+R）跳缓存 |
| 项目长时间卡在 running 但任务无进度 | LLM 调用挂起或 MCP 不响应。watchdog 60s 内会 force-stall。手动可调 `POST /workflow/projects/<id>/abort` |
| Crew 任务的某一 step 失败 | UI 子卡片 → IO 查看 看 `out.json` 里的 captured，或对话按钮问诊断助手。后端 log 搜 `crew.step_failed` |
| LLM 调用超时 | 90s 硬超时，见 `infra/llm/gateway.py:LLM_CALL_TIMEOUT_SECONDS`。Anthropic 在 CN 网络访问困难时，把 task 切到 deepseek 等本地可达 provider |
| `mycrew.db-wal` 文件几 MB 不下 | 不会自动清；连接时会 `wal_checkpoint(TRUNCATE)`。如果一直涨：有进程没干净退出。`recover-db-lock.ps1` |
| `events` 表过大 | janitor 每 6h 跑一次，全局 30 天 / 项目 10k 行保留 |
| 老项目 / 老 agent 消失 | PM v4 wipe 一次性执行过（commit `393bf59`），备份在 `data/db/mycrew.db.pre-v4.<ts>` |

---

## 第六节 · 未来规划（按触发条件查）

| 触发条件 | 该读 |
|---|---|
| **打算发版打包** | [roadmap/phase3-deferred-to-packaging.md](./roadmap/phase3-deferred-to-packaging.md) D1 LLM key 加密 + D2 Tauri CSP |
| **要接外部 Agent / OpenClaw** | [roadmap/mcp-export-server-design.md](./roadmap/mcp-export-server-design.md) + [openclaw-integration-plan.md](./roadmap/openclaw-integration-plan.md) |
| **要做 SaaS 化** | phase3-deferred D3-D4（状态外移 + tenant_id） |
| **要做下次完整 audit** | [roadmap/next-audit-prep.md](./roadmap/next-audit-prep.md) 60s 快照 + 8 个新维度 |
| **出现线上事故** | next-audit-prep §4 "下个 Top 5 候选" 看是否覆盖 |
| **要补测试** | [roadmap/phase2-backlog.md](./roadmap/phase2-backlog.md) B1（5 个零测试的服务） |
| **MCP 调用频繁失败** | phase2-backlog B2（断路器） |
| **想升级 crewai 版本** | phase2-backlog B3 + 补 crewai_runner 测试（B1） |
| **想加多用户 / 多租户** | phase3-deferred D4（PG + tenant_id 全表） |

---

## 第七节 · 索引维护

### 何时更新本文件

| 变更类型 | 必须更新本文件吗 |
|---|---|
| 新加 service / component | 是 — 加到 §2 主题表 + §4 关键文件表 |
| 新加 REST 端点 / WS 事件 | 否（spec/API.md 是权威） — 但本文 §2.3 / §2.7 引用要核对 |
| 新加 iteration / roadmap 文档 | 是 — 加到 §1 速查 或 §6 未来规划 |
| 新加 ADR | 是 — 加到 §2.x 对应主题的链接 |
| 出现新的故障 + 修法 | 是 — 加到 §5 故障排查 |
| 出现新的"我想做 X" 操作 | 是 — 加到 §3 |

### 链接策略

- 优先链向**稳态文档**（`spec/*`），其次链向 **iteration log**（带日期，可能过时）。
- 代码位置用相对路径 `backend/...`，不带行号（行号会变；要看具体行去 IDE 用 Go to Definition）。
- 跨章节引用用 `§<编号>` 而非锚点，避免重排后失效。

### 检查清单（每月一次）

- [ ] §1 速查：链接是否都活
- [ ] §2.6 安全模块：有没有新加的还没列
- [ ] §3.1 / 3.2：有没有新增的"加东西"路径漏写
- [ ] §5 故障排查：有没有新症状没归档
- [ ] §6 未来规划：触发条件是否仍合理
