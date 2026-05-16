# Phase 2 Backlog — 已记录、未本轮执行

> 来源：`docs/iterations/2026-05-16/architecture-audit.md` Section 3 Phase 2。
> 本轮（2026-05-16 落地的修复）已经执行的项目：见每项「状态」字段。
> 仍待办的项目按"触发条件"分组，决定何时拉起来做。

---

## 本轮已执行（不再列入未来事项）

| 项 | 落地位置 | 测试 |
|---|---|---|
| FastAPI middleware 加 X-Request-ID + 结构化日志自动注入 | `backend/bootstrap/app.py` `_request_id_middleware` + `infra/request_context.py` | `tests/test_request_id.py` (4 cases) |
| `_output_capture._planner_outputs` 加 TTL 清理 | `backend/src/tools/builtin/local/_output_capture.py` `_evict_expired` (任务 1h / planner 4h) | `tests/test_output_capture_ttl.py` (4 cases) |
| 异常吞咽审计：`patch_blueprint` 4 处 bare except 改成显式异常类型 + warn 日志 | `backend/src/tools/builtin/local/patch_blueprint.py:203, 310, 314, 328` | 既有测试通过 |

---

## 仍待办（按触发条件分组）

### B1 — 补 5 个零测试的关键 service

| Service | 公开函数数 | 现有测试 | 建议测试范围 |
|---|---|---|---|
| `crewai_runner` | 11 | 0 | tool registry resolution、run_task_with_crewai 的 LLM provider 兼容路径 |
| `watchdog_svc` | 7 | 0 | reconcile_all_orphans_on_startup、stall-detect 命中条件 |
| `planner_orchestrator` | 5-phase 编排 | 0 直接 | _validate_assignments、_assemble_draft_blueprint |
| `planner_cache_svc` | 10 | 0 | start_round / get / update / set_phase_output 的并发安全 |
| `blueprint_writer` | 2 | 0 | write_blueprint_to_disk 的 pending 目录回退 |

**触发条件**：任何一个 service 出现线上 incident 时优先补；否则放到下一个 quiet sprint。

**工作量估算**：每个 service 3 个 happy-path 用例 ≈ 0.5 天，全部完成 ≈ 2.5 天。

---

### B2 — MCP 工具熔断（连失 3 次后 60s 内不再尝试）

**问题**：`infra/mcp/pool.py:99-112` 实现了连接级 backoff，但单个工具调用没有断路器。一个挂掉的 MCP 服务，所有工具调用都得等连接超时（默认 8s）才失败 — 影响整个 Crew 的进度。

**建议方案**：
- `mcp_pool.call()` 加 `_circuit_state: dict[server_id, (failure_count, opened_at)]`。
- 连失 3 次 → state="open"，60s 内直接抛 `MCPCircuitOpen`，不去尝试。
- 60s 后 → state="half-open"，下一次调用试一次，成功则关回 closed，失败再开 60s。

**触发条件**：出现"MCP 服务挂了导致整个 Crew 卡 30 秒以上"的实例 1 次以上时上。

**工作量**：1 天（含测试）。

---

### B3 — `pip-audit` + `npm audit` 集成

**问题**：当前没有自动化 CVE 扫描。手动跑也行但容易忘。

**建议方案**：
- 后端：`pip-audit` 作为 pre-commit hook，每次 commit 前快速扫描 `pyproject.toml` 锁定的版本。
- 前端：`npm audit --audit-level=moderate` 作为 pre-commit hook。
- 周期：每月手动一次完整扫描，写迭代日志。

**触发条件**：
- CI/CD 接入时（如果开 GitHub Actions）→ 直接放进流水线。
- 否则：每月 1 号手动跑一次。

**工作量**：0.5 天（CI 接入）/ 5 分钟（手动跑一次）。

---

### B4 — 前端补 5 个核心 hook 的 vitest 测试

**问题**：65 个 TS/TSX 文件，0 个单元测试，只有 1 个 Playwright smoke。

**最该补的 5 个**（覆盖每个核心 hook 的 1 个 happy-path）：

| Hook | 用途 | 建议测试 |
|---|---|---|
| `useChatQueue` | Plan Maker 对话队列 + 单飞 | enqueue/abort/error path |
| `usePmState` | PM v3/v4 5-phase log 拉取 | initial poll → WS subscribe |
| `useEvent` | WS 事件订阅 | listener 注册/清理、ref 稳定性 |
| `useProjectQuery` | 项目列表 + 项目详情 | invalidation 行为 |
| `useBackendConnection` | 后端端口发现 + 心跳 | reconnect schedule |

**触发条件**：等 PM v4 的 Crew 子卡片 + WS sub_step 的真机回归测稳定后做（防止测试和实际行为不一致返工）。

**工作量**：1.5 天（含 vitest 配置补全 + 5 个测试）。

---

### B5 — JSON 列规范化反序列化器

**问题**：`agents.tool_ids` / `crews.agent_ids` / `tools.params_schema` 在 schema 里是 JSON-encoded 字符串，但 `agent_svc` / `crew_svc` 没有中心化反序列化。每个调用者各自 `json.loads + try/except`，覆盖率不均匀。

**建议方案**：
- 在 `agent_svc._decode` / `crew_svc._decode` 加入这些字段到 JSON_FIELDS 常量。
- `tool_svc` 加 `_decode` 处理 `params_schema`。
- 统一 fallback 行为：`[]` for 列表字段、`{}` for 对象字段。

**触发条件**：出现"agent 工具列表读出来是字符串导致 N/A"类 UI bug 时立刻上；否则下次 service 改造时顺手做。

**工作量**：0.5 天（含 fixture 数据补 JSON-string 形式）。

---

### B6 — 索引补齐

**问题**：`chat_sessions.task_id` / `chat_messages.session_id` / `events.task_id` 没独立 index。

**建议方案**：写 `0014_indexes_addition.py`，三条 `CREATE INDEX IF NOT EXISTS`，无 downgrade。

**触发条件**：
- 任何按 `task_id` 查 chat / event 出现明显延迟时；
- 或下次有 schema migration 顺手加（不必为这事单独发版）。

**工作量**：15 分钟。

---

## 状态汇总

- 本轮**已执行 3 项**（request_id middleware / 输出捕获 TTL / patch_blueprint 异常细化）
- **待办 6 项**（B1-B6），每项都标了触发条件，避免提前 over-engineer
- 全部完成后预期健康度 +6 分（72 → 78），但需要至少 1 次真实 incident 来排优先级
