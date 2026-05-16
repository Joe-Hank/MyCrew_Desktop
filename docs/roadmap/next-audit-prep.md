# 下次技术审核准备文档

> **干什么用**：给下次（无论是我自己还是别人）做技术审核的人一份"开局即知道该往哪看"的地图。
> **什么时候读**：准备启动下一次完整 audit 时，**先读这一页**，再决定要不要展开。
> **当前状态**：2026-05-16 17:00 撰写，对应代码快照 commit `37d8469`。

---

## 第一节 — 60 秒快照

| 指标 | 上次 audit (`2026-05-16 早`) | 落地后（本文撰写时） |
|---|---|---|
| 代码规模 | 后端 221 `.py` / 前端 65 `.ts·.tsx` | 后端 230 / 前端 65（+9 后端，含新增 service + 测试） |
| 后端测试通过 | 196 | **258**（+62 含 Stage A–G + Phase 1/2 修复） |
| 前端单元测试 | 0 | 0 |
| Top 5 风险关闭 | 0 / 5 | **5 / 5**（SQL 注入、WS 鉴权、并发锁、事务、test 修复） |
| 健康度评分 | 72 | **预估 82**（待下次完整 audit 复算） |
| 测试覆盖增量 | — | +8 个测试文件 / +49 个用例 |

### 自上次 audit 已经做的

- Phase 1 全部 5 项执行 — 见 [`audit-followup-2026-05-16.md`](../iterations/2026-05-16/audit-followup-2026-05-16.md)
- Phase 2 中确定/必要的 3 项执行（request_id middleware / capture TTL / patch_blueprint 异常）
- Phase 3 全部归档（标了触发条件，不动）
- 文档分四档重组：`spec/` / `iterations/` / `roadmap/` / `ADR/` / `archive/`

### 没动的

- Phase 2 剩余 6 项（见 [`phase2-backlog.md`](./phase2-backlog.md)）
- Phase 3 全部 7 项（见 [`phase3-deferred-to-packaging.md`](./phase3-deferred-to-packaging.md)）
- MCP server + OpenClaw 集成（设计草案已立，等触发）

---

## 第二节 — 上次 audit 没覆盖的高维度（**重点：下次审应该补**）

上次 audit 是 11 维（架构 / 数据 / 健壮性 / 安全 / …）但都聚焦**代码**。下面 8 个维度上次没碰，下次至少挑 3-4 个展开。

### A. 业务功能验证 — Crew 真的能产出真东西吗？

| 检查项 | 当前状态 | 验证方法 |
|---|---|---|
| Art Crew 真出 PNG（不是空文件占位） | **未真机验证**（Stage H 跳了） | 用 ComfyUI MCP 跑一个真实 Unity 项目，看 `Assets/Sprites/` 落地的 PNG 是否有效图 |
| System Implementation Crew 真出 .cs（含正确方法签名） | 未验证 | 跑一个 PlayerController 任务，看 Unity 控制台编译错误数 |
| Scene Assembly Crew 真能加载场景 | 未验证 | 跑一个 Pac-Man 类项目，开 Unity 看场景是否能直接 Play |
| QA step 验收真的拒绝缺失文件 | 已单测 (`emit_output_paths`) | 端到端验证 — agent emit 假路径时 QA 抛错 |
| `synth_8bit_sfx` 在真 Unity 里能识别为 AudioClip | **未真机验证** | 跑一个 Audio Crew，让 Unity Developer 把 wav 配为 AudioClip 后看 inspector |

**审核建议**：下次审核**必须先跑 1 个真实端到端 Unity 项目**（plan H 跳过的事情）。没跑过的"通过测试"等于零。

### B. 用户体验 / 错误恢复路径

| 检查项 | 当前状态 |
|---|---|
| 错误消息可操作性（用户读了知道下一步） | `last_error_kind` 8 种已有映射；但 PM v4 新增的 Crew 失败（如某 step 挂）的恢复指引未写入 `KIND_HEADLINES` |
| 重试按钮覆盖度 | 任务级有；**子卡片级"从 Step N 重试"未实现**（Q5 设计了但 Stage F 没落地完，得查实际行为） |
| 长时无响应的兜底（agent 卡死、MCP 不响应） | watchdog `stalled` 状态 + 90s LLM timeout；但**前端没有 "你已经等了 N 分钟，要不要中止" 的提示** |
| 删除项目的撤销窗口 | 没有 — 删除即真删除（含 .mycrew/ 文件） |

### C. 性能基准（**完全缺失**）

上次 audit 维度 8 说"基准缺失"。下次审核前应该建好：

**建议 baseline 指标**：
| 指标 | 测量方法 | 目标 |
|---|---|---|
| 后端冷启动到 ready | `MYCREW_DEV=0 python -m bootstrap.main` 计时 | < 5s |
| 项目创建 → 任务列表渲染 | 浏览器 Network 看 POST /projects 到 GET /projects/{id} 完成 | < 1s |
| Crew 4-step 跑一次的 token 用量 | 跑同一个 Art Crew 任务 5 次，取均值 | 待定 baseline |
| WS 重连成功率（10 次断网） | 手动 kill backend → 等重连 | 100% |
| 50 个 task 项目的 canvas 渲染帧率 | DevTools Performance tab | ≥ 30fps |

**实施**：写一个 `backend/scripts/bench.py` 跑后端启动 + API latency；前端用 Playwright 测渲染时间。

### D. 国际化 / 可访问性

| 检查项 | 当前状态 |
|---|---|
| UI 文案全中文 | ✓ 是 — 没做 i18n |
| 错误消息全中文 | ✓ 是 |
| ARIA / 键盘导航 | **未审核** — Tauri 弹窗 + xyflow canvas + drawer 都没 role/aria-label 系统化 |
| 屏幕阅读器友好 | **不友好** |
| 高对比度模式 | 没适配 |

如果未来面向更广用户（含视障 / 多语言），这是大坑。

### E. 打包发版前的安全门槛

下次审核如果在**首次打包前**做，必须额外查：

| 检查项 | 风险 |
|---|---|
| Tauri capabilities allowlist 是否最小化 | 默认开太宽 = 攻击面增大 |
| Tauri CSP 启用 | 已禁用（`csp: null`）— 见 [`phase3-deferred-to-packaging.md` D2](./phase3-deferred-to-packaging.md#d2--tauri-端-csp-启用--能力-allowlist) |
| LLM key Stronghold 加密 | 当前明文 DB — 见 [`phase3-deferred-to-packaging.md` D1](./phase3-deferred-to-packaging.md#d1--llm-api-key-加密落盘) |
| 代码签名证书 | 未配置 |
| 自动更新流程 + 签名验证 | 未设计 |
| `mycrew.db.pre-v4.*` 备份文件清理策略 | wipe_v4 会留备份文件，没有自动清理；用户磁盘会堆积 |

### F. 法律 / 数据合规

| 检查项 | 当前状态 |
|---|---|
| 用户的 LLM API key 法律归属 | 桌面 app 单用户本地 — 风险低，但**首次启动需要 EULA 说明** |
| 项目 / 任务数据存储位置 | 本地 SQLite，没向外发送 — 但**LLM 调用本身会把 task.detail / blueprint 发给 OpenAI / DeepSeek**。EULA 必须明示这点。 |
| `inception_messages` 历史中可能存在的敏感对话 | 用户与 Plan Maker 的对话存 DB；**没有用户主动删除路径** |

### G. Bus factor / 可维护性

| 检查项 | 当前状态 |
|---|---|
| 单一开发者的项目 | ✓ — Joe-Hank 一人 |
| ADR 完整度 | 8 条已锁，覆盖关键决策 |
| 复杂模块的 onboarding 难度 | `_planner_orchestrator.py`（5-phase 编排）+ `workflow_svc.py`（核心调度）是最长的两个文件，注释质量高（90%+ WHY-comment），但缺一份"如何从零理解 PM v3/v4"的 walkthrough 文档 |
| 代码 review 流程 | 无（单人项目） |
| CI/CD | 无 |

**建议**：写 `docs/spec/PLANNER-WALKTHROUGH.md`（30 分钟读完，从 inception session 到 task 执行的全流程图）。

### H. 依赖供应链 / AI 输出质量

| 检查项 | 当前状态 |
|---|---|
| `pip-audit` 跑过吗 | **没**（审计建议但未实施） |
| `npm audit` 跑过吗 | **没** |
| crewai 升级节奏 | 锁在 ≥0.100.0 但实际版本可能更高，需要看 lockfile |
| LLM prompt injection 测试 | 没系统测过；只手测过几条 |
| Agent 输出质量回归集 | **没** — 没有"同一个 prompt 跑 10 次取一致性"的基准 |

---

## 第三节 — 风险监视清单（本轮引入的新风险）

每条都是"现在没事但可能后面爆"的事项，下次审核时核实是否爆了。

| # | 风险 | 引入位置 | 监视方法 | 状态 |
|---|---|---|---|---|
| R1 | `crud.py` SQL fragment 拒绝合法但奇怪的 WHERE 子句 | `infra/repo/crud.py:50-95` | 找 5xx 错误日志里包含 `SqlFragmentError` 的，超 1 次/天 → 拒绝过严 | 待监视 |
| R2 | WS 4401 disconnect 让前端进入 reconnect-loop | `frontend/src/net/ws.ts:31-50` | 看用户报告"网络一直转圈"；后端 backoff 已经在 net/api.ts 实现，应该没事 | 待监视 |
| R3 | `_output_capture` TTL 1h 太短，长任务（Crew 8 步逐步走 60min+）payload 被过期清掉 | `_output_capture.py:32` | 一旦真出现 `pop_output → None` 但任务确实跑过，就是 TTL 短了 | 待监视 |
| R4 | `WorkflowService` lock 字典 `_project_locks` 在 cleanup 之外没驱逐路径，长寿命进程可能累积 | `workflow_svc.py:130-141` | 进程 RAM 监视；目前只在 cleanup 时驱逐 | 低优先 |
| R5 | session token 写入 stdout 的方式被前端 / Tauri 读取链断了 | `bootstrap/app.py:118-120` + `frontend/src/net/ws.ts:39-48` | Tauri 侧没改 — 现在前端是直接 HTTP fetch `/auth/ws_token`，stdout 输出仅作冗余备份 | 已验证 |
| R6 | `request_id_middleware` 与 audit middleware 顺序敏感 | `bootstrap/app.py:223-230` | 改任何一个 middleware 顺序前**必读**注释；测试覆盖了 audit 的 rid 继承 | 待监视 |
| R7 | `wipe_v4` 一次性脚本已运行，删了用户老项目 + 老 agent | `bootstrap/wipe_v4.py` | 看用户报告"我老项目不见了"；备份 `mycrew.db.pre-v4.20260516_043543` 在 `data/db/` 还在 | 已知影响，可恢复 |
| R8 | `compare_digest` 时序攻击窗口 | `api/ws.py:81` 用了 `secrets.compare_digest` 已防 | ✓ | 已防御 |
| R9 | OpenClaw 集成预案假设 OpenClaw 是 MCP 兼容的 | [`openclaw-integration-plan.md`](./openclaw-integration-plan.md) | 实际接入前确认 OpenClaw 实际有什么协议 | 待用户确认 |

---

## 第四节 — 下个 Top 5 候选（如果不动手会成为下次的 P0/P1）

按"现在没爆 + 但下一次审核很可能升级"排：

1. **Crew 长链路的可观测性** — 一个 Crew 跑 4-8 步，前端只看到 sub_step WS 事件；如果 step 2 失败，用户能看到原因吗？现在 `task.sub_step` 事件的 error 字段被传过去但前端 sub-card UI 显示的是状态点，不是错误细节。
   - 验证方法：故意让 Concept Artist step 失败，看 sub-card 是否显示明确错误。
   - 修复成本：1 天（sub-card 加 error tooltip + 错误日志 expand 区）。

2. **MCP 工具调用没有断路器** — Phase 2 backlog B2 标记但没做。Unity Bridge 挂 → 整个 Crew 卡 8s/次。
   - 验证方法：跑 Crew 时强制 kill Unity MCP，看 Crew 是否能在 30s 内放弃。
   - 修复成本：1 天。

3. **`crewai_runner` 零测试，但是 LLM 调用主入口** — Phase 2 backlog B1。任何对 CrewAI 接口的破坏性变更（升 crewai 版本）都无法被 CI 抓到。
   - 验证方法：把 `requirements.txt` 里的 crewai 改成 0.99 跑一遍 import smoke 看会不会挂。
   - 修复成本：1 天（5 个 happy path 测试）。

4. **没有 `iterate_existing` 在 PM v4 下的兼容测试** — 双轨路径已建（workflow_svc 看 performer_kind），但是没测试 case 验证 "v3 创建的项目（agent_id-only）能在 v4 后端继续跑"。
   - 验证方法：手动 INSERT 一行 performer_kind=NULL 的 task，看 `_run_agent` 是否走老路径。
   - 修复成本：0.5 天。

5. **审计事件表 `events` 没有 LIMIT — `query_events` 默认返回全部** — `events_svc.query_events:103-138`，如果 30 天保留期 + 高频 broadcast 累到 100k 行，UI 一次拉就 OOM。
   - 验证方法：cron 生成 100k 测试事件，调 GET /events，看响应时间。
   - 修复成本：0.25 天（加 LIMIT 1000 默认）。

---

## 第五节 — 迭代草案（下一轮）

按时间窗组织。每个标了"为什么现在做"和"触发条件"。

### 候选迭代 X — "Crew 真机化"（**最高优先**）

- **目标**：跑通真实端到端 Unity 项目（Stage H 跳过的事），验证 8 个 Crew 都能产出真东西。
- **关键产出**：
  1. 1 个 Pac-Man-class Unity 项目跑通，含 ComfyUI 真生 sprite + Audio Crew 真合成 wav + System Impl Crew 真出 .cs + Scene Assembly 真装配场景。
  2. 跑后看 Unity 控制台编译错误数 = 0。
  3. 跑后用户能直接 Play 场景。
- **预计工作量**：2-3 天（前提：本地已配 ComfyUI + Unity MCP）。
- **触发**：用户决定做第一次真机验证时。
- **不做的代价**：所有 PM v4 落地都是"测试通过但没人跑过"。

### 候选迭代 Y — "Crew 子卡片错误显示完善"

- **目标**：Top 5 候选 #1 的修复。
- **产出**：
  - sub-card 加 error tooltip / expandable 错误详情区。
  - `KIND_HEADLINES` 加 Crew step 相关的失败描述。
  - "从 Step N 重试" 按钮（Q5 设计了但 Stage F 未落地完）。
- **预计**：1-1.5 天。
- **触发**：迭代 X 跑通后立刻做（用户会立刻发现错误信息不清晰）。

### 候选迭代 Z — "可观测性 + 性能 baseline"

- **目标**：建好下次 audit 能引用的 benchmark + 监控基础。
- **产出**：
  - `backend/scripts/bench.py`（4-5 个 perf 指标）。
  - 异常计数器（`SqlFragmentError` / `PermissionDenied` / `LLM_CALL_TIMEOUT` 累计）放进 `/api/v1/health` 响应。
  - `pip-audit` + `npm audit` 写一个 `scripts/run-security-scan.sh`。
- **预计**：2 天。
- **触发**：迭代 X+Y 完成后；或决定首次发版打包前 2 周。

### 候选迭代 W — "打包准备"（**与发版强绑定**）

- **目标**：把 [`phase3-deferred-to-packaging.md`](./phase3-deferred-to-packaging.md) 里的 D1 + D2 全部完成。
- **产出**：LLM key Stronghold 加密 / Tauri CSP 启用 / Tauri capabilities 收紧 / 代码签名 / 自动更新。
- **预计**：5-7 天。
- **触发**：决定首次发版的时间点（不在此之前**不要碰**，否则跟开发期 UI 改动冲突）。

---

## 第六节 — 下次审核执行手册

### 起手 30 分钟

1. 读本文件（5 分钟）→ 知道上次发生了什么、哪里没动。
2. 跑全套测试基线（5 分钟）：
   ```bash
   cd backend && python -m pytest --tb=no -q
   cd ../frontend && npx tsc --noEmit && npx vite build
   ```
   记录当前 pass 数 + build size，与本文件第一节对比。
3. 看最近一次 audit 落地后的 commit 历史（5 分钟）：
   ```bash
   git log --since="2026-05-16 13:00" --format="%h %s"
   ```
4. 看本文件第二节 8 个新维度，**选 3-4 个**重点展开（按当前业务阶段挑）。

### 并行 Explore 模式

复制上一次审核用过的并行 agent 模板（4 个 Explore agent 同时跑），加入新维度：

```
Agent 1: 业务功能 (维度 A) + 用户体验 (维度 B)
Agent 2: 性能基准 (维度 C) + 依赖供应链 (维度 H)
Agent 3: 打包准备 (维度 E) + 法律合规 (维度 F) — 仅在打包前 audit 时启用
Agent 4: 维护性 (维度 G) + 代码级回归（自上次 audit 来的新代码扫一遍）
```

每个 agent 输出 800-1500 字 + 文件路径行号引用。

### 输出文档命名

`docs/iterations/<YYYY-MM-DD>/architecture-audit.md` — 跟上一次同名同地，保持时间线。

### 收尾

落地后写 `docs/iterations/<YYYY-MM-DD>/audit-followup.md`，按 Phase 1/2/3 分档，**每条标"已执行"/"已记录"/"等触发"** — 跟上一轮 [`audit-followup-2026-05-16.md`](../iterations/2026-05-16/audit-followup-2026-05-16.md) 同格式。

---

## 索引 — 当前所有审核相关文档

> 这是入口。每条都点过去能直接看上下文。

### 上一轮（2026-05-16）的产出

- [上轮 audit 全文](../iterations/2026-05-16/architecture-audit.md) — 11 维度 + Top 5 + 路线图（含 MCP / OpenClaw 草案）
- [上轮 audit followup](../iterations/2026-05-16/audit-followup-2026-05-16.md) — 落地了哪 8 项 / 没动哪 13 项

### 当前 backlog（按触发条件分组）

- [Phase 2 backlog](./phase2-backlog.md) — 6 项优化，每项标了触发条件 + 工作量
- [Phase 3 deferred](./phase3-deferred-to-packaging.md) — 7 项延后事项，跟打包/SaaS 化时机绑

### 设计草案

- [MCP export server](./mcp-export-server-design.md) — `mycrew-export-mcp` 的 6 工具 + 4 资源 + 2 prompt
- [OpenClaw 集成](./openclaw-integration-plan.md) — A/B/C 三方向决策树

### 稳态参考

- [spec/ARCHITECTURE.md](../spec/ARCHITECTURE.md) — 当前架构
- [spec/STORAGE-MAP.md](../spec/STORAGE-MAP.md) — DB schema + 文件落盘约定
- [spec/API.md](../spec/API.md) — REST + WS 契约
- [ADR/](../ADR/) — 8 条已锁定决策

### 历史归档（**不再更新**，仅供翻历史）

- [REVIEW_2026-05-12](../archive/REVIEW_2026-05-12.md) — 上一轮 audit 之前的更早审查
- [PM v3 plan 跟 grill](../iterations/2026-05-15/) — PM v3 设计细节
- [PM v4 plan 跟 grill](../iterations/2026-05-16/pm-v4-plan.md) — PM v4 设计细节

---

## 第七节 — 自检清单（给做下次审核的我）

复制粘贴用，跑前打勾。

```
[ ] 已读本文件第一节（60 秒快照）
[ ] 已跑后端测试基线，记录数字
[ ] 已跑前端 tsc + vite build，记录数字
[ ] 已 git log 看过自上次 audit 以来的 commit
[ ] 已决定本次 audit 选哪 3-4 个新维度（第二节）
[ ] 已决定要不要把第四节的 "下个 Top 5 候选" 升级到 P0/P1
[ ] 已并行启动 4 个 Explore agent（如沿用上次模板）
[ ] audit 文档写完后，更新本文件第一节的 "60 秒快照" 数字
[ ] audit followup 写完后，更新 phase2-backlog / phase3-deferred 的 "本轮已执行" 字段
[ ] 检查 docs/README.md 的索引是否需要加新条目
```

---

## 最后一句

**审核的价值不在分数，而在"哪些假设需要重新验证"**。上次审了代码层；下次要审业务层（迭代 X）+ 长寿命运行的可观测性（迭代 Z）。代码层只要继续保持 Phase 1 + Phase 2 的纪律，不会成为下一次的 Top 5。
