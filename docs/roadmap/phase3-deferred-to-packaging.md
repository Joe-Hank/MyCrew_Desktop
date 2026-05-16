# Phase 3 与打包时机绑定的延后事项

> 来源：`docs/iterations/2026-05-16/architecture-audit.md` Section 3 Phase 3。
> 原则：**"会留坑的现在做、可以等到打包再做的放后面"**。
> 本文件锁定每一项**何时必须**做、**为什么现在不做**、**到时如何收尾**。

---

## 现在已经做的（避免留坑）

以下事项虽然在 Phase 3 列表里，但**现在不做就会留坑**，所以本轮已经处理：

| 项 | 现状 |
|---|---|
| `WorkflowService` 加 `asyncio.Lock` per project | ✅ 本轮 P1.2 完成 — 多用户/双击场景下产生重复 harness 的可能性归零 |
| `create_project_with_tasks` 补偿事务 | ✅ 本轮 P1.3 完成 — 半完成项目残留 DB 的可能性归零 |
| `crud.py` SQL 注入加固 | ✅ 本轮 P1.4 完成 — 任何把请求参数透传到 WHERE 的未来代码都会被拒绝 |
| WS session token 鉴权 | ✅ 本轮 P1.5 完成 — 同机其他进程/浏览器 tab 不能再连 WS |

---

## 与打包时机绑定的延后事项

### D1 — LLM API key 加密落盘

**现状**：`llm_providers.api_key_ref` 列名暗示是 secret store 的引用，实际写的是 key 本体（`backend/services/llm_svc.py:174`）。备份文件（`mycrew.db.pre-v4.*`）就是裸 DB 拷贝。

**为什么不现在做**：
1. 需要 Tauri Stronghold 插件集成（Tauri 侧 + Rust 侧动作），跟前后端解耦的当前节奏不匹配。
2. 现在用户全是开发期单机，DB 文件物理隔离已经够。
3. 改完要做 migration：把现存 plaintext key → Stronghold-resolved ref。本地热改不会丢，但**首次打包发布**就是天然分水岭 —— 老安装基本都会清空数据。

**到时如何收尾**（打包前 1 周）：
1. 加 Tauri Stronghold 插件 + 生成主密钥（开机解锁/PIN）。
2. 后端加 `infra/secrets.py`：`resolve_key_ref(ref: str) -> str`，把 `llm_providers.api_key_ref` 当作真正的 ref。
3. 写 migration 0015：扫描每条 `llm_providers` 行，若 `api_key_ref` 看起来是裸 key（不是 ref 格式），用 Stronghold 存一份，把 DB 列换成新 ref。
4. 删除 `_v4_reset_done.flag` 那类一次性脚本里"备份成 plaintext db"的代码 → 改成"加密备份"。

**触发**：决定发版打包时立刻拉起来，不要等用户问"我的 key 安全吗"。

---

### D2 — Tauri 端 CSP 启用 + 能力 allowlist

**现状**：`tauri.conf.json:24` `csp: null`，CSP 显式关闭。当前没有 XSS 入口（没有 `dangerouslySetInnerHTML`、没有 markdown 渲染外部内容），所以"现在不上 CSP"暂时无害。

**为什么不现在做**：
1. 没有具体威胁（前端不渲染 LLM 的原始 HTML）。
2. CSP 一旦开启严格策略，常见的 inline style / 内联 SVG 都会被拒绝，需要逐条调；本轮 UI 还在大改（PM v4 / Stage F 刚落地），不是稳态。
3. Tauri 2.x 的能力 allowlist（如 dialog、fs、shell）改了语义，建议**打包配置定型时一并设**。

**到时如何收尾**（打包前 2 周）：
1. 启用 CSP：`default-src 'self'; connect-src 'self' ws://127.0.0.1:* http://127.0.0.1:*; img-src 'self' data:; style-src 'self' 'unsafe-inline'`（unsafe-inline 给 Tailwind 用，明确写注释为啥保留）。
2. Tauri capabilities：明确列允许的 commands（`pickFolder`、`openExternal`、`fs:read-file` 限制到工程目录）。
3. 把 `tauri.conf.json` 改成生产配置后跑一遍 e2e Playwright，确认 UI 没崩。

**触发**：发版前 2 周（给联调 + 调样式留时间）。

---

### D3 — `_active / _runners / _outputs` 状态外移到 SQLite 持久化

**现状**：进程崩 → 所有运行中 harness 蒸发；只剩 DB 上的 `state="running"` 标记。`watchdog_svc.reconcile_all_orphans_on_startup` 能 force-stall 解锁，但用户得手动重跑。

**为什么不现在做**：
1. 当前是桌面单进程，崩溃概率本就低；用户重启即可。
2. 状态外移需要 schema 设计 + cross-task event sourcing，比补丁式修复**贵 10×**。
3. **现在不做不会留坑** —— 真正受影响的是"长流程 Crew 任务跑到一半崩溃 + 用户气炸"那种 SLA 场景，桌面应用没那么严苛。

**触发**：
- 出现 1 次"Crew 跑了 30 分钟突然崩溃"事故 → 立刻拉起来；
- 或决定 SaaS 化 / 多实例部署 → 必须先做。

**工作量**：3-5 天（含 schema migration + 重放逻辑 + 测试）。

---

### D4 — 切 PostgreSQL + 加 `tenant_id` 全表

**现状**：SQLite 单文件，0 个 `tenant_id` 列。

**为什么不现在做**：
- 桌面单用户，没多租户需求。
- 加 `tenant_id` 是结构性改造（每张大表 + 每条查询），不可能小成本。

**为什么列在 Phase 3**：
- **新增表时同步加 `tenant_id` 占位**是预防留坑的关键。本轮已经审计了所有现存表，没有遗漏；下次加表时按规矩走。

**触发**：
- 明确 SaaS 化的产品决策（不能由开发者单方面发起）。
- 触发后流程：写 RFC → 用户确认 → 启动 8-12 周专项。

---

### D5 — OpenTelemetry / Sentry 类托管接入

**现状**：结构化日志 + 内部 `events` 表，没有告警 / 没有外部 trace。

**为什么不现在做**：单团队 1 用户的项目，没有"事故需要立刻看板上聚合"的迫切性。

**触发**：团队 ≥ 5 人 或 月线上事故 ≥ 1 次时上。

**工作量**：2-3 天（OpenTelemetry SDK 接入 + 选一个 backend 平台）。

---

### D6 — iterate_existing 全面 PM v4 化

**现状**：Q12 决定保留 v3 行为；workflow_svc.dispatch 已支持双轨读（performer_kind='crew' → 走 _run_crew；否则走老路径）。

**为什么不现在做**：PM v4 刚落地，等"在真实 Unity 项目上跑稳 1 个月"再统一执行链路。提前重构 = 同时调两条变化轴，bug 难定位。

**触发**：PM v4 上线后稳定运行 ≥ 4 周，且未出现 v4 专属的执行路径问题。

**工作量**：2-3 天。

---

### D7 — 权限矩阵从 9 个 kind 拓展到路径粒度

**现状**：`permissions` 表有 `pattern` 字段但 `permission_guard.require_permission` 不使用。

**为什么不现在做**：用户没碰到过 agent 写错路径事故。

**触发**：出现"agent 把文件写到 Assets/ 之外、需要更细的允许列表"那种事故的瞬间上。

**工作量**：1 天（permission_svc.check 加 pattern 匹配 + 测试 + UI 上把 pattern 列变可编辑）。

---

## 总结

| 序号 | 项 | 触发 |
|---|---|---|
| D1 | LLM key 加密 | **打包发版前 1 周** |
| D2 | Tauri CSP + capabilities | **打包发版前 2 周** |
| D3 | 状态外移到 DB | 1 次崩溃事故 / SaaS 决策 |
| D4 | PG + tenant_id | SaaS 化产品决策 |
| D5 | OpenTelemetry | 团队 ≥ 5 或月事故 ≥ 1 |
| D6 | iterate_existing v4 化 | PM v4 稳定 4 周 |
| D7 | 权限路径粒度 | 写错路径事故 |

**Phase 3 的核心信号**：不要为了"未来可能要做"而提前下手；每一项都标了清晰的触发条件，不到触发不动。
