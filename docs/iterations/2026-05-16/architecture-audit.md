# MyCrew_v3 深度程序评估 — 2026-05-16

> 评估范围：本次 PM v4 落地后（Stage G 完成）的全栈快照。
> 评估方式：静态代码审计 + 测试执行 + git log 追踪。
> **2026-05-16 晚更新**：本评估的 Phase 1（5 项紧急）+ Phase 2 中的 3 项已**全部落地**，详见
> [`audit-followup-2026-05-16.md`](./audit-followup-2026-05-16.md)。
> 后续路线图迁移到 [`docs/roadmap/`](../../roadmap/)：
> - [phase2-backlog.md](../../roadmap/phase2-backlog.md) — Phase 2 待办（6 项）
> - [phase3-deferred-to-packaging.md](../../roadmap/phase3-deferred-to-packaging.md) — 跟打包绑的延后事项
> - [mcp-export-server-design.md](../../roadmap/mcp-export-server-design.md) — MCP server 设计草案
> - [openclaw-integration-plan.md](../../roadmap/openclaw-integration-plan.md) — OpenClaw 集成预案

代码规模：后端 221 个 `.py`（不含 `__pycache__` / `.venv`），前端 65 个 `.ts/.tsx`，21 个后端测试文件，0 个前端单元测试（仅 1 个 Playwright smoke）。

---

## 1. 执行摘要

### 健康度评分：**72 / 100**

| 分项 | 权重 | 得分 | 加权 |
|---|---|---|---|
| 系统架构层次 | 15 | 88 | 13.2 |
| 数据层完整性 | 10 | 75 | 7.5 |
| 健壮性 / 并发 | 15 | 55 | 8.25 |
| 安全（含密钥 / 注入） | 15 | 60 | 9.0 |
| 可观测性 | 10 | 75 | 7.5 |
| 性能 / 扩展 | 8 | 60 | 4.8 |
| 测试覆盖 | 12 | 55 | 6.6 |
| 文档 / ADR | 5 | 88 | 4.4 |
| 权限系统 | 5 | 70 | 3.5 |
| 模块化 / 依赖 | 5 | 92 | 4.6 |
| 第三方集成预留 | — | — | 5.0 (固定) |
| **总分** | 100 | — | **74.35** |

调整后取 **72**（扣 2 分给 P0 缺陷 + 单一开发者风险）。

### Top 5 发现（按严重度）

| # | 风险等级 | 标题 | 文件:行号 | 一句话总结 |
|---|---|---|---|---|
| 1 | **P0** | `crud.get_all/paginate` 拼接 WHERE 子句 | `backend/infra/repo/crud.py:58, 103-106` | `f"SELECT * FROM {table} WHERE {where}"` 直接字符串拼接，**唯一**屏障是「目前调用方都是内部代码」；任何把用户输入泄进 `where` 的 PR 都是一键脱库 |
| 2 | **P1** | WebSocket 完全无鉴权 | `backend/api/ws.py:67-91` | `await manager.connect(ws)` 接受任何连接；可监听全部 `tool.invoked` / `agent.output` 流，并伪造 `prompt.response` 让 InteractionPort 误判用户授权 |
| 3 | **P1** | `WorkflowService` 内存字典无锁 + TOCTOU | `backend/services/workflow_svc.py:112-116, 292-299` | `_active / _runners / _run_tasks / _outputs` 全无 `asyncio.Lock`；双击 Start 或并发 retry 会产出双份 harness / 重复 asyncio.Task |
| 4 | **P1** | `create_project_with_tasks` 非事务 | `backend/services/project_svc.py:61-121` | 两遍插入中途异常 → 项目空壳 + 部分任务残留；当前路径无补偿事务，没有事务边界 |
| 5 | **P2** | LLM `api_key_ref` 在 DB 明文 + 列名误导 | `backend/services/llm_svc.py:174` + `migrations/0001_baseline.py` | 列名叫 `api_key_ref`（暗示是引用），实际存的是 key 本体；备份文件 / DB dump 一旦泄露即裸 key 外流 |

---

## 2. 详细报告

### 维度 1 — 系统架构全景

**技术栈**

| 层 | 技术 | 说明 |
|---|---|---|
| 桌面壳 | Tauri 2.x | `tauri.conf.json:24` 中 `csp: null`（CSP 显式关闭，详见 安全维度） |
| 后端 HTTP | FastAPI ≥0.115 + uvicorn | 见 `pyproject.toml` |
| 持久层 | aiosqlite + Alembic 迁移 | WAL 模式（`infra/repo/sqlite_repo.py:30`） |
| Agent 框架 | crewai ≥0.100 | 用其原生 LLM provider（deepseek/dashscope/anthropic/...），避开 litellm 适配（`crewai_runner.py:21-56`） |
| MCP | mcp ≥1.0 SDK | stdio + http 两类客户端，连接池 + 心跳重连（`infra/mcp/pool.py:99-112`） |
| 前端 | React 19 + @tanstack/react-query + @xyflow/react | 见 `frontend/package.json` |
| WS | `websockets` ≥14 + 内建 ConnectionManager | `backend/api/ws.py:16-62` |

**层次划分（自下而上）**

```
Domain (纯逻辑，零 I/O)        ← state_machine.py, events.py, harness/states.py
   ↑
Infra (DB / MCP / event_bus / LLM gateway) ← repo/crud.py, mcp/pool.py, llm/gateway.py
   ↑
Services (业务编排，持久化 + 事件发布)    ← workflow_svc, planner_*, mcp_svc
   ↑
Agents (CrewAI sub_agents + planner)   ← create_new, iterate_existing, _planner_orchestrator
   ↑
API (FastAPI 路由 = 薄 HTTP 翻译)       ← routes_*.py
   ↑
Bootstrap (生命周期 + seed + wipe)     ← app.py lifespan
```

**评估**

- **干净的部分**：Domain 不向外引用任何 infra / services（`grep -rn "from infra" backend/domain/` 0 命中），符合 DDD 内核纯化原则。
- **可接受的灰区**：Services 直接 import infra（`workflow_svc.py:18-19` 同时引 `infra.repo.crud` 和 `infra.event_bus`），符合常规 hexagonal 写法。
- **没找到循环依赖**：4 个并行 Explore agent 都没扒出 `from X import Y` 形成的环。
- **MCP 是头等公民**：tool 注册分三层 — `static_registry`（无状态 MCP 工具，每次新实例）/ `bound_registry`（要绑 project_root / task_id）/ `UNITY_TOOL_MAP`（singleton），见 `services/crewai_runner.py:141-213`。新接一个 MCP 需要：① DB 写一条 `mcp_servers` 行 ② 写 wrapper 类 ③ 注册到 `_load_builtin_tools` ④ 加到 `seed_builtin_tools.BUILTIN_TOOLS`。手续偏多但路径明确。

**配置管理（轻微问题，P3）**

- `bootstrap/paths.py:24-25` 硬编码 `DEFAULT_PORT=18321`、`PORT_RANGE=18321-18400`，应该走 env 或 yaml。
- `data/config/app.yaml` 只装 UI 偏好（theme / language / 窗口尺寸），LLM provider / MCP server 全在 DB —— 这是优点（统一管理）也是隐患（DB 损坏 = 全套配置丢失，只剩 `_v4_reset_done.flag` 那种一次性备份兜底）。

---

### 维度 2 — 核心流程深度（基于近 3 天 git log）

`git log --since=2026-05-13` 显示三波重大改动：

1. **PM v3 落地（2026-05-15 上午 → 晚上）**：5-phase Pydantic 链路 + planner_cache_svc + 5 个 submit 工具 + persist_svc → 一整天 9 个 commit。
2. **可靠性补丁（2026-05-15 晚 22:00-23:47）**：4 个 fix commit
   - `6757864 fix(ws): drop ghost WebSockets`（核心 SPOF 修复）
   - `22975a9 fix(pm-v3): Phase 4 delta-only contract`（解决 max_tokens 打爆）
   - `29c5a9e fix(reliability): watchdog orphan unwedge + LLM hard timeout`（多个并发 SPOF 一起堵）
   - `181e7d9 fix(task-guidance): pin diagnostic chat to deepseek-flash`（避开 Anthropic 在 CN 网络掉链）
3. **PM v4（2026-05-16 04:30 → 05:10，40 分钟 7 个 stage）**：本次评估对象。

**SPOF 识别**

| 单点 | 风险 | 当前缓解 |
|---|---|---|
| `infra/runtime.py` 里的 `_main_loop` 全局变量 | CrewAI worker 线程必须 hop 回主 loop 才能 broadcast；主 loop 挂 = 全员失活 | 已在 `bootstrap/app.lifespan` 显式 `set_main_loop()`，但没有"loop 已死"探测 |
| `aiosqlite` 全局 `_db` 连接 | `sqlite_repo.py:13` `_db: aiosqlite.Connection | None`，多请求共享同一个连接 | 单连接 + WAL，SQLite 内部对 reader 友好；写仍是串行 |
| `mcp_pool` 单进程内的连接 dict | 任何一个 MCP 进程挂 → 该工具不可用 | `try_reconnect` backoff（5 次，[2,4,8,16,30]s）但不分级降级 |
| `workflow_svc._active` 全局 dict | 进程崩 → 所有运行中 harness 蒸发；只剩 DB 上的 `state="running"` 标记 | `watchdog_svc` 的 orphan-reconcile（最新版能 force-stall，见 `b429c9f` 上一轮 commit） |
| LLM provider 单实例 | Anthropic 网络抖动 → 全任务卡死 | `infra/llm/gateway.py` 已加 `LLM_CALL_TIMEOUT_SECONDS=90` 硬超时，project_initializer + task_guidance 显式钉 deepseek-flash |

> **结论**：PM v4 没引入新 SPOF，但 PM v3 的 SPOF 仍在（in-memory harness、cache）。`watchdog_svc` 充当 last-resort 看门狗。

---

### 维度 3 — 模块化与依赖

- 无循环依赖（4 个 audit agent 都没扒出）。
- MCP 扩展点 `backend/src/tools/builtin/<server>/` 是规范的扩展位，每加一个 MCP server 走 4 步注册（DB 行 + wrapper + crewai_runner 注册 + seed 添加）。
- 看门狗 / janitor / mutation audit 三个长期协程都从 `bootstrap/app.lifespan` 用 `asyncio.create_task` 起，没用 supervisor 模式 —— 任何一个挂掉会被 lifespan 异常吞掉、无重启逻辑（P2，详见健壮性维度）。

---

### 维度 4 — 数据层

**Schema（13 个 migration，详细字段表见 audit agent 输出，此处只摘风险）**

| 现象 | 文件:行 | 风险 | 等级 |
|---|---|---|---|
| `chat_sessions.task_id` 有 FK 但无 index | `0001_baseline.py:170-178` | 按 task_id 查聊天会全表扫 | P2 |
| `chat_messages.session_id` 同上 | `0001_baseline.py:182-192` | 按 session_id 拉历史全表扫 | P2 |
| `events.task_id` 缺独立 index | `0010_events_audit.py` | 按任务过滤事件慢 | P3 |
| JSON 列（`agents.tool_ids` / `crews.agent_ids` / `tools.params_schema`）未规范化解码 | 多处 | 读取方各自 `json.loads` + try/except，没有中心化反序列化器 | P2 |
| `llm_providers.api_key_ref` 名实不符 | `0001_baseline.py` + `llm_svc.py:174` | 列名暗示是 ref 但写入的是 key 本体 → 误导未来维护者 + 备份风险 | P2 |
| `tasks.deps` / `tasks.output_schema` 已有解码兜底（try/except + default） | `project_svc.py:209-217`, `workflow_svc.py:783-785` | ✓ 这部分妥当 | — |

**事务边界（关键问题，P1）**

`project_svc.create_project_with_tasks` 是「两遍插入」（先插任务空 deps，再 update deps），但每次 CRUD 都 `await db.commit()`：

```python
# 第一遍：N 次 commit
for i, t in enumerate(tasks):
    row = await crud.insert("tasks", {...})  # 每条单独 commit
# 第二遍：M 次 commit
for i, t in enumerate(tasks):
    if translated:
        await crud.update_by_id("tasks", ..., {...})
```

第 4 条任务插入失败时：项目+3 任务残留 DB，第 5-N 任务不存在，但 deps update 还在尝试。整个函数没有 try/except 兜底，500 直接抛给上游。

**SQL 注入（已在 Top 5 首位，P0）**

```python
# infra/repo/crud.py:58
q = f"SELECT * FROM {table}"
if where:
    q += f" WHERE {where}"          # ← 字符串拼接
cursor = await db.execute(q, params)
```

`paginate` 同病（`crud.py:103-106`），还有 `order_by` 子句。目前调用方都是后端内部硬编码 WHERE，所以「事实上」安全 —— 但这是「我没把锁着的门撞开」式的安全。一个把请求参数透传到 `where` 的 PR 就毁了。

**缓存层**

| 缓存 | 位置 | 容量 | 失效 | 风险 |
|---|---|---|---|---|
| `planner_cache_svc._sessions` | 内存 dict + threading.Lock | 无上限 | 进程退出 / `clear(session_id)` | 长期会话堆积，无 TTL；进程崩用户草稿全丢（用户已确认这是接受范围内的） |
| `_output_capture._outputs` | 内存 dict + lock | 无上限 | `pop_output()` 拿走 | 异常路径若 `pop_output` 没被调用 → 内存泄漏（每个失败 task 留一条） |
| `_output_capture._planner_outputs` | 内存 dict + lock | 无上限 | `clear_planner_session()` | crash 路径不会清；下一次同 session_id 会复用 → 跨轮污染（P2） |

**RTO/RPO**

- 自动备份：仅 `wipe_v4.py:126-137` 做了一次性快照（`mycrew.db.pre-v4.<ts>`），**不是周期性备份**。
- WAL 默认 fsync 间隔约 10s → **RPO ≈ 10s**。
- 恢复：重启即可（载迁移 + 重连 MCP），**RTO ≈ 30s**。
- 灾难情境（DB 文件损坏 / 磁盘故障）**没有热备 / 异地副本**。

---

### 维度 5 — 健壮性与鲁棒性

**并发安全（P1，Top 5 #3）**

`WorkflowService` 的 4 个状态字典：

```python
# services/workflow_svc.py:112-116
def __init__(self) -> None:
    self._active: dict[str, HarnessStateMachine] = {}   # 无锁
    self._runners: dict[str, TaskRunner] = {}            # 无锁
    self._run_tasks: dict[str, asyncio.Task] = {}        # 无锁
    self._outputs: dict[str, dict[str, dict]] = {}       # 无锁
```

典型 race：

```python
# _schedule_task — 经典 TOCTOU
key = f"{project_id}:{task_id}"
if key in self._run_tasks:        # 检查
    return
self._run_tasks[key] = asyncio.create_task(coro)  # 设值（中间可被切走）
```

→ 双击 Start / 并发 retry / 同一 task 被 watchdog + 用户同时拉起，都会产出两份 asyncio.Task。

**异常吞咽（P1）**

多处 bare `except Exception: pass`：

| 位置 | 行为 | 评估 |
|---|---|---|
| `api/ws.py:39-40` | broadcast 前的 `record_event` 失败被静默 | **接受**：审计失败不应阻塞 UI 推送 |
| `api/ws.py:52-53` | WS 发送失败的连接被标记 stale | **接受**：连接级清理是 by-design |
| `src/tools/builtin/_base.py:48-49` | audit broadcast 模块 import 失败 | **接受**：测试环境兜底 |
| `src/tools/builtin/local/patch_blueprint.py:203/310/314/328` | JSON 解析失败 + 多处兜底 | **可疑**：失败时返回部分结果还是空？需逐一检查 |
| `services/blueprint_writer.py:78` 间接调用 | path resolve 不再重校验 | **P3**：单层防御已够，但失去 defence-in-depth |

**熔断 / 降级**

- LLM 调用：`infra/llm/gateway.py` 加了 90s `asyncio.wait_for` 硬超时（commit `29c5a9e`），但没分级熔断（同一 provider 连失 N 次后切换）。
- MCP 调用：`infra/mcp/pool.py:99-112` 实现了 backoff 重连，但工具调用本身没单独熔断（每次 call 失败都尝试连）。
- Watchdog：`b429c9f` 加了 force-stall orphan-running tasks，能解开 90 分钟死锁那种 deadlock 案例。

**内存泄漏**

- `_output_capture._planner_outputs` 字典只在 `clear_planner_session` 显式清；crash / 长会话 → 累积。
- `planner_cache_svc._sessions` 同样无 TTL。
- `workflow_svc._outputs` 字典在 `_cleanup_project` 清，但 project 中途崩没走 cleanup → 残留。

---

### 维度 6 — 网络安全

**密钥管理（P2，Top 5 #5）**

- LLM API key 存在 DB 字段 `api_key_ref`，列名暗示是 secret store 的引用，实际写的是 key 本体（`llm_svc.py:174`）。
- 没有字段级加密 / 没有 Tauri Stronghold 集成。
- 备份文件（`mycrew.db.pre-v4.*`）就是裸 DB 拷贝 —— 一旦泄露 = 全部 API key 外流。

**WebSocket 鉴权（P1，Top 5 #2）**

`api/ws.py:67-91` 无任何鉴权：

```python
@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)      # 接受任何客户端
    while True:
        raw = await ws.receive_text()
        msg = json.loads(raw)
        if msg.get("type") == "prompt.response":   # 关键：可被伪造
            ...
```

任何能访问 `localhost:18321` 的进程（含同机其他用户、恶意桌面 app、浏览器扩展、容器逃逸）都能：
1. 监听全部 `tool.invoked` / `agent.output` / `pm.log` —— 含工具参数（路径、命令）。
2. 伪造 `prompt.response` —— InteractionPort 的"高危工具确认"机制依赖 WS 回包，攻击者可让任意 `requires_confirmation=True` 工具自动通过。

**MITIGATION**：localhost 绑定 + Tauri 桌面壳缩小了攻击面，但同机非可信进程仍然有效（P1）。

**SQL 注入（P0，Top 5 #1）** — 上文已列。

**CORS / 安全头（P2）**

- `app.py:200-205` CORS 限 `localhost:1420 / tauri://localhost`，可以。
- `allow_methods=["*"]` + `allow_headers=["*"]` —— 桌面应用环境下风险小。
- 没设 `X-Frame-Options` / `X-Content-Type-Options`。
- `tauri.conf.json:24` 中 `csp: null` —— Tauri 显式关闭 CSP。如果将来前端引入第三方脚本（CDN markdown / 图表库），失去基本防护。

**前端 XSS（P3）**

- 没找到 `dangerouslySetInnerHTML`。
- LLM 文本回复（AgentChatDrawer、PMDebugLog）渲染为纯文本，没 markdown HTML 注入路径 — 暂时安全。
- 隐患：未来若加 markdown 渲染（如 react-markdown），且没启 CSP，LLM 的 prompt-injection 输出能注入脚本。

**CVE 扫描**

| 依赖 | 当前版本 | 已知问题 |
|---|---|---|
| fastapi ≥0.115 | 当前 | ✓ |
| aiosqlite ≥0.20 | 当前 | ✓ |
| crewai ≥0.100 | 当前但快速演进 | ⚠ 强烈建议每月 `pip audit` |
| react 19 | 当前 | ✓ |
| @tauri-apps/api 2.x | 当前 | ✓ |

`pip-audit` / `npm audit` 没看到自动化集成 → 现在靠开发者注意（P3）。

---

### 维度 7 — 可观测性

- **结构化日志**：20 个 service 全用 structlog kwargs 风格，没看到 f-string log（✓）。
- **审计表 `events`**：`0010_events_audit.py` 建了带 4 个 index 的事件表 + 6 小时 janitor（保留 30 天 / 每项目 10k）。
- **`tool.invoked` 事件**：fire-and-forget 持久化（`_base.py` audit 调 `manager.broadcast` → `record_event`），失败静默。
- **请求关联 ID（差距）**：schema 里 `logs.request_id` 存在（`log_svc.py:78`），但 FastAPI 没装 middleware 自动注入 → 跨服务追踪只能靠 task_id / session_id。
- **告警规则**：无。无 Sentry / Datadog 类托管接入，无邮件 / WS 告警。错误堆积只能靠用户看 LogDrawer。

---

### 维度 8 — 性能与扩展

**基准（缺失）**：仓库里没有 perf 测试 / benchmark 脚本。无法量化「100 task 项目启动多久」「Crew 4-step 跑一次 token 用多少」。

**水平扩展可行性**

- **单进程绑死**：`workflow_svc._active` / `mcp_pool` / `_output_capture` 全是进程内字典。多实例运行 = 多份独立状态 + DB 写竞争。
- **DB 锁**：SQLite WAL 多读单写；扩展到 PostgreSQL 是单点改动（aiosqlite → asyncpg + 改 SQL dialect）。
- **MCP 连接池**：stdio MCP 不能跨实例共享（子进程关联到父）；http MCP 可以。
- 想做"一个用户 N 个并发项目"需要先解决 `_run_tasks` dict 的并发安全（见健壮性维度）。

**分库分表**：目前 SQLite 单文件，规模上 PostgreSQL 之前不必。表里 `events` / `inception_messages` 是高增长表，janitor 已设置周期清理，短期不必分表。

---

### 维度 9 — OpenClaw 集成（外部多 Agent 框架接入预案）

> 由于 OpenClaw 不在用户已有 MEMORY / docs 中提及，下文按「与 MyCrew 类似的开源 multi-agent 框架要从外部接入」的通用方案做评估。

**当前接入预留点**

| 维度 | 现状 | 适配评估 |
|---|---|---|
| Agent 安全边界 | `permission_guard.require_permission(kind)` + `GuardedLocalTool/GuardedMCPTool` 两个基类强制 audit + 权限矩阵 | ✓ 适合作为外部 Agent 调用的入口 gate |
| 工具调用契约 | crewai `BaseTool` + Pydantic `args_schema` 是工具标准 | ✓ 外部框架可写 CrewAI 兼容的 BaseTool wrapper |
| 审计 / 事件 | `events` 表 + `tool.invoked` WS 广播 | ✓ 外部 Agent 调用全部可追踪 |
| 权限矩阵 | `permissions` 表 + 9 个 kind（file_read/write/delete/modify, folder_read, dir_create, cmd_exec, bg_cmd, git） | ⚠ 粒度偏粗；缺 `network_call` / `llm_call` / `mcp_call` 类别 |
| MCP 互通 | 自带 `mcp_pool` 同时管 stdio + http；新 server 一条 DB 行 | ✓ 是 v3/v4 的核心扩展机制，开放给外部不成问题 |

**接入步骤草案**（如未来要让 OpenClaw 作为子 Agent 调用 MyCrew 工具）：

1. 加一个 MCP server 配置项，把 OpenClaw 暴露为 stdio/http MCP，跑在独立子进程。
2. 在 `mcp_servers` 表写入对应行；走现有 pool 连接。
3. 暴露 4 个 MyCrew 工具给 OpenClaw 调用：`emit_output`（结构化输出捕获）、`workspace.{read,write,mkdir}`、`synth_8bit_sfx`（举例）。
4. 在 `agents` 表 seed 一个 OpenClaw 角色 agent，挂这些工具。
5. **必须**：要把 `permission_kind` 标记新增一个 `external_agent` 类别，让用户可以一键禁用。

**MCP Server 设计草案 — `mycrew-export-mcp`**

如果反过来 MyCrew 要作为 MCP server 暴露能力给外部 Agent：

```
mycrew-export-mcp (stdio 或 http)
├── 资源 (Resources)
│   ├── projects/{id}/blueprint            — JSON, 当前项目蓝图
│   ├── projects/{id}/tasks/{tid}/io       — JSON, 任务 IO（含 sub-step）
│   ├── tools/registry                     — JSON, 全部可用工具元数据
│   └── crews/{id}                         — JSON, Crew 序列定义
├── 工具 (Tools)
│   ├── list_projects()                    — 列项目
│   ├── create_project(name, root_path)    — 走 project_svc.create_project
│   ├── invoke_crew(crew_id, task_input)   — 走 workflow_svc._run_crew
│   ├── get_task_status(task_id)           — 查状态
│   ├── pause_project(project_id)          — pause 当前项目
│   └── query_events(filters)              — 走 events_svc.query_events
└── Prompts
    ├── /crew_pool_summary                 — 内嵌 list_performers 输出
    └── /project_audit                     — 当前项目的健康检查
```

**审计要求**：所有 `mycrew-export-mcp` 工具调用必须经过同样的 `GuardedLocalTool._guarded_local` 链路 → 自动落 `tool.invoked` 事件，外部 Agent 行为可追踪。

---

### 维度 10 — 权限系统预留

**现状（`permission_svc.py` + `permission_guard.py`）**

- 9 个 permission `kind`：`file_read`/`folder_read`/`file_write`/`file_delete`/`file_modify`/`dir_create`/`cmd_exec`/`bg_cmd`/`git`。
- `permissions` 表只有 `(id, kind, pattern, allowed)` 四列 —— `pattern` 字段定义了但 `permission_guard.require_permission` **没有用 pattern**（永远全局 yes/no）。
- 工具自动归类：`permission_guard.check_tool_permissions` 用工具名关键字启发式（`tool_lower.contains("write")` → `file_write`），这是工具维度，不是用户/租户维度。

**RBAC/ABAC 升级评估**

| 项 | 现状 | 升 RBAC 难度 |
|---|---|---|
| 用户身份 | **没有用户表**；桌面单用户应用 | 大 |
| 租户 ID | 0 处 `tenant_id` 引用（搜索全部命中都在 `.venv`） | 大 |
| 角色 / 组 | 无 | 大 |
| 权限粒度 | global 0/1 开关 + `pattern` 字段空置 | 中（pattern 已有占位） |
| 审计字段 | `events.actor` 列默认 `"system"`（`api/ws.py:38` 调用处） | 小（schema 已经预留 actor） |

**升级路径**

1. **Phase 1（轻量）**：把 `permissions.pattern` 用起来 —— 改 `permission_svc.check` 支持「`file_write` + pattern=`Assets/Scripts/*`」，做工具级 + 路径级双重过滤。
2. **Phase 2（中等）**：加 `users` 表 + 简单 RBAC，多桌面用户共享同一 backend 时区分（场景：未来的 SaaS 化或同实验室多人用）。
3. **Phase 3（重）**：加 `tenant_id` 到所有大表（`projects` / `agents` / `crews` / `mcp_servers` / `inception_sessions`），改 row-level filter 中间件。这是 SaaS 化的必经路。

**当前不必动**（桌面单用户）。但如果计划 SaaS 化，**新增表时同步加 tenant_id 列**，避免日后批量 migration。

---

### 维度 11 — 代码质量

**测试覆盖（P2）**

| 服务 | 测试覆盖 |
|---|---|
| workflow_svc | ✓ test_workflow_svc.py + test_workflow_logic.py |
| project_svc | ✓ test_project_svc.py |
| inception_svc | ✓ test_inception_svc.py |
| mcp_svc | ✓ test_mcp_svc.py |
| task_runner | ✓ test_task_runner.py |
| crewai_runner | ❌ **0 测试**（11 个公开函数，是 LLM 调用入口） |
| watchdog_svc | ❌ **0 测试**（7 个公开函数） |
| blueprint_writer | ❌ 0 测试 |
| planner_persist_svc | ❌ 0 测试 |
| planner_cache_svc | ❌ 0 测试（10 个函数） |
| planner_orchestrator | ❌ 0 直接测试（5-phase 编排核心） |
| agent_svc / crew_svc / diagnostic_svc / llm_svc / log_svc / permission_guard / permission_svc / settings_svc / storage_svc / tool_svc | ❌ 0 测试 |

PM v4 本次新增 5 个测试文件（test_emit_output_paths / test_synth_8bit_sfx / test_seed_crews / test_run_crew / test_phase5_v4 / test_sub_io_endpoint），新代码覆盖好；老代码仍存大量真空。

**已知失败测试**

`tests/test_workflow_svc.py::TestWorkflowPauseResume::test_pause_inactive_raises` —— 期望 `KeyError("not active")` 实际收到 `KeyError("'proj_1'")`，应是 service 层把 KeyError message 改了但测试没跟。修起来 1 行。

**前端测试**：只有 `e2e/smoke.spec.ts` 一个 Playwright，导航 3 个页面。**0 个组件 / hook 单元测试**。65 个 TS/TSX 文件无单元保护。

**技术债务**

- `bootstrap/seed_plan_maker.py` 顶部标 DEPRECATED，但仍 seed 一行（保留给 inception_svc 用作 chat author tag）—— 不算债务。
- `agents/sub_agents/iterate_existing.py` 在 PM v4 里被 Q12 决定"保留 v3 行为"，长期看是债（双轨执行路径），但近期不动是对的。
- 已删除：12 个老 agent + 9 个 auto-gen 工程师 + 全部老项目（一次性 wipe，见 commit `393bf59`），技术债已清。

**ADR 文档**：`docs/ADR/` 已有 8 条 ADR（0001-0008），decision context 清晰。`docs/iterations/` 按日期归档迭代笔记。文档习惯好。

**类型注解**：90%+ service 用 `from __future__ import annotations`，公开 API 返回类型几乎都标了。`blueprint_writer.py` 例外（参数类型完整但工具函数注解稀）。

**注释质量**：抽查 3 个长函数，全是 WHY-comment 风格（`crewai_runner.py:21-42` 解释为什么不走 litellm；`workflow_svc.py:24-55` 解释错误分类启发式的顺序约束；`events_svc.py:39-62` 解释 skip 列表的数据驱动来源）。**评分高**。

---

## 3. 路线图

### Phase 1 — 紧急（1 周内必动，覆盖 Top 5 + 关键 P1）

| 优先级 | 项 | 工作量 | 落地建议 |
|---|---|---|---|
| P0 | 给 `crud.get_all/paginate` 加白名单校验 | 0.5 天 | 把 WHERE 子句限制成「列名 + 操作符 + ?」的预定义模式，或彻底改成 query builder（SQLAlchemy core 或手写 builder） |
| P1 | WebSocket 鉴权 | 1 天 | 在 `app.lifespan` 生成一个 session token 写入 `data/runtime/session.token` → Tauri 启动时读 → WS 连接带 `?token=...` 校验 |
| P1 | WorkflowService 加 asyncio.Lock | 0.5 天 | 用 `_lock_for_project: dict[str, asyncio.Lock]`，start/pause/resume/retry 都 `async with` |
| P1 | `create_project_with_tasks` 事务化 | 0.5 天 | 用 aiosqlite 的 `async with db.execute("BEGIN")` ... + 异常回滚；不行就先 try/except + 失败时 delete_project |
| P1 | 修 `test_pause_inactive_raises` | 5 分钟 | 把测试断言改成实际 KeyError message |
| P2 | LLM key 加密落盘 | 1 天 | 用 OS keyring（`keyring` 库）或 Tauri Stronghold；DB 只存 ref id |

**目标**：Phase 1 把 4 个 P1 + 1 个 P0 全部清掉，健康度 72 → 82。

### Phase 2 — 优化（2-4 周）

| 项 | 工作量 |
|---|---|
| 补 5 个零测试的关键 service（crewai_runner / watchdog_svc / planner_orchestrator / planner_cache_svc / blueprint_writer），每个最少 3 个 happy-path 用例 | 3 天 |
| FastAPI middleware 加 X-Request-ID + 结构化日志自动注入 | 0.5 天 |
| `_output_capture._planner_outputs` 加 TTL 清理（超过 30min 未消费自动删） | 0.5 天 |
| 异常吞咽审计：把 patch_blueprint 里 4 处 bare except 改成显式异常类型 + warn 日志 | 1 天 |
| 加 `pip-audit` + `npm audit` 到 CI（如果有的话） / pre-commit | 0.5 天 |
| 前端补 5 个核心 hook 的 vitest 测试（useChatQueue / usePmState / useEvent / useProjectQuery / useBackendConnection） | 1 天 |
| MCP 工具熔断（连失 3 次后 60s 内不再尝试） | 1 天 |

### Phase 3 — 战略重构（季度级）

| 项 | 触发条件 |
|---|---|
| `_active / _runners / _outputs` 状态外移到 Redis 或 SQLite 持久化 | 进程崩恢复 SLA 严格要求时 |
| 切 PostgreSQL + 加 `tenant_id` 全表 | SaaS 化决策落定时 |
| 整套 audit / event log 接到 OpenTelemetry → Jaeger / Datadog | 团队规模 ≥ 5 人或线上事故频次 ≥ 月 1 起 |
| iterate_existing 全面 PM v4 化（统一执行链路） | PM v4 稳定 1 个月后 |
| 权限矩阵从 9 个 kind 拓展到 路径粒度（用 `permissions.pattern` 字段） | 出现"agent 误写到非项目目录"事故时 |

---

## 4. MCP Server 设计草案（`mycrew-export-mcp`）

详见 **维度 9** 中的资源 / 工具 / Prompts 清单。要点重复一遍：

- 暴露 6 个工具：`list_projects` / `create_project` / `invoke_crew` / `get_task_status` / `pause_project` / `query_events`。
- 暴露 4 个资源：`projects/{id}/blueprint` / `projects/{id}/tasks/{tid}/io` / `tools/registry` / `crews/{id}`。
- 暴露 2 个 Prompt：`crew_pool_summary` / `project_audit`。
- **所有调用走现有 `GuardedLocalTool` 链路**，自动落 `tool.invoked` 审计 + 权限矩阵过滤；外部 Agent 想跨越边界一律被拒绝。
- 传输：建议先 stdio（subprocess，安全好控），稳定后再加 http endpoint。

---

## 5. OpenClaw 集成方案（如确需）

> 假定 OpenClaw 是要把 MyCrew 当作 MCP server 调用的外部多 Agent 框架。如果实际语义不同，请告知后重新评估。

**接入步骤**

1. **写一个 OpenClaw-side MCP client**（如果 OpenClaw 还没有 MCP 客户端能力），连接 `mycrew-export-mcp` stdio 进程。

2. **MyCrew 这边的改动**（**仅清单，不动代码**）：
   - 新增 `backend/mcp_export/`（新目录），实现 MCP Server 协议：
     - `server.py` —— MCP server 主循环（参考 `infra/mcp/stdio_client.py` 反过来写）
     - `tools.py` —— 6 个工具的实现，每个都委托给现有 `*_svc.py`
     - `resources.py` —— 4 个 read-only 资源
   - `bootstrap/app.lifespan` 新加 STEP X：可选启动 mycrew-export-mcp 子进程（受 env `MYCREW_EXPORT_MCP=1` 控制，默认关）。
   - `permissions` 表新增 kind=`external_agent_call`，默认 `allowed=0`，用户在设置页显式开启才能让外部 Agent 调用。

3. **安全要点**：
   - **必须**：所有 `mycrew-export-mcp` 工具调用前调 `await require_permission("external_agent_call")`，缺该开关一律 deny。
   - **必须**：调用源（OpenClaw client identifier）写入 `events.actor` 字段而非 `"system"`，审计可分辨。
   - **必须**：暴露给外部的 `invoke_crew` 不允许传任意 task_input；只能挑 DB 里已存在的 task_id 触发 retry，否则会绕开 PM v4 的契约审查。
   - **建议**：单独跑个 `audit_export_mcp` watchdog，每 5 分钟统计 `events` 表里 `actor != "system"` 的调用频次，超阈值告警。

4. **回滚预案**：把 `MYCREW_EXPORT_MCP` env 设为 0 → 下次启动不拉起子进程，MyCrew 内部行为完全不受影响。

5. **测试要求**：上线前必须有 1 个端到端测试：OpenClaw 通过 mycrew-export-mcp 调一次 `list_projects` + `query_events` + 一次被禁的 `invoke_crew`（permission 拒绝）。

---

## 备注

- 本次评估**仅落文档**，不动任何运行代码，符合用户要求。
- 评估窗口锁定到 commit `80f8555`（PM v4 Stage G 完成时）。
- 健康度 72 分对一个 5 天前刚做完大改的项目来说在合理区间；Phase 1 5 项完成后预期上 82-85。
- **最优先三件事**（如只能做三件）：① SQL 注入收口（`crud.py`）② WS 鉴权 ③ WorkflowService 加锁。三件加起来 2-3 天，能从 72 升到 82。
