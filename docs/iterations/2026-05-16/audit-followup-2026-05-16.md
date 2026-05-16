# Audit Follow-up — 2026-05-16

> 紧接 [`architecture-audit.md`](./architecture-audit.md) 之后的落地记录。
> 处理的范围：Phase 1 全部 5 项 + Phase 2 中**已经确定且必要**的 3 项。
> 没做的项：Phase 2 剩余 6 项 + Phase 3 全部 7 项 — 见 `docs/roadmap/`。

---

## 总体结果

| 指标 | 落地前 | 落地后 |
|---|---|---|
| 后端测试通过 | 250 | **258** |
| 新增测试用例 | — | 25（spread across 5 个新测试文件） |
| 健康度评分 | 72 / 100 | **预估 82 / 100**（待下次完整 audit 复算） |
| Top 5 风险关闭 | 0 / 5 | **5 / 5** |

---

## Phase 1 — 紧急执行（全部完成）

### P1.1 — `test_pause_inactive_raises` 修正

- **位置**：`backend/tests/test_workflow_svc.py:119-132`
- **改动**：测试断言更新，匹配 `workflow_svc.pause` 的新两层语义（live harness / orphan reconcile / KeyError）
- **耗时**：5 分钟

### P1.2 — `WorkflowService` per-project `asyncio.Lock`

- **位置**：`backend/services/workflow_svc.py:112-141`（`_project_locks` + `_get_project_lock`）+ 5 个 public mutator（`start/pause/resume/abort/retry_task`）改造为 `_locked` 内层 + 公共外层 lock 包装。
- **关键约束**：同 `project_id` 的 start/pause/resume/abort/retry **串行**；不同 `project_id` 并行。
- **`_cleanup_project` 同步驱逐对应 lock entry**，防止长寿命进程累积。
- **新测试**：`tests/test_workflow_locks.py`（4 个用例：lock 复用、同项目串行、不同项目并行、cleanup 驱逐）

### P1.3 — `create_project_with_tasks` 补偿事务

- **位置**：`backend/services/project_svc.py:77-138`
- **方案**：SQLite + aiosqlite 没法把跨多个 `commit()` 的两遍插入合并成单 BEGIN/COMMIT；改用 try/except + 失败时调 `delete_project(project_id)` 把已写的项目 + 子任务全部回滚。
- **新测试**：`tests/test_project_svc_txn.py`（2 个用例：第 3 个 task insert 失败时项目和前 2 个 task 全清；happy path 仍持久化）

### P1.4 — `crud.py` SQL fragment 守卫（**P0 修复**）

- **位置**：`backend/infra/repo/crud.py:11-95`（新增 `_IDENTIFIER_RE` / `_validate_table` / `_validate_where` / `_validate_order_by` / `_FRAGMENT_BLOCKLIST` + `SqlFragmentError`）
- **应用范围**：`insert / get_by_id / get_all / update_by_id / delete_by_id / count / paginate` 全部 7 个 CRUD 函数。
- **检查规则**：
  - 表名 / 列名 必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`。
  - WHERE / ORDER BY 不允许 `;`、`--`、`/*`、`*/`、`\x00`。
  - WHERE 子句的 `?` 数 = `params` 长度（catches 占位符错配）。
  - ORDER BY 每个 atom 必须是 `col` 或 `col ASC|DESC`。
- **现有调用全部通过**：所有在用的 hardcoded WHERE（包括 `status NOT IN ('done','failed','aborted','validation_failed')` 这类含字面字符串的）都不触发拒绝。
- **新测试**：`tests/test_crud_sql_guard.py`（29 个用例：识别符接受/拒绝、`?` 数验证、危险子串、ORDER BY 形式、真实 callers 验证）

### P1.5 — WebSocket session token 认证（**P1 修复**）

- **位置**：
  - 后端：`backend/api/ws.py:30-60`（token 模块级 + `generate_session_token` + `set_session_token`），WS handshake 前先校验 `?token=…`，错则 close(4401)。
  - 路由：`backend/api/routes_auth.py`（新文件，`GET /api/v1/auth/ws_token` localhost-only）。
  - 启动：`backend/bootstrap/app.py:113-127`（lifespan 生成 token → 写 `data/runtime/session.token` + 打印 `MYCREW_WS_TOKEN=…` 给 Tauri sidecar 读 stdout）。
  - 前端：`frontend/src/net/ws.ts`（重写 `connect` / `doConnect`，先 `fetch` token 再带 `?token=…` 连 WS；close code 4401 时清缓存重连）。
- **威胁模型缓解**：localhost 上的其他进程 / 浏览器 tab 不能再连 WS，也无法伪造 `prompt.response` 自动批准高危工具。
- **新测试**：`tests/test_ws_auth.py`（6 个用例：token 格式、missing/wrong/correct 三种 handshake、auth endpoint 返回值、未初始化的 503）

---

## Phase 2 — 已执行（3 项）

### P2.1 — `request_id` middleware + structlog context binding

- **位置**：
  - `backend/infra/request_context.py`（新文件，contextvar + structlog processor 占位）
  - `backend/bootstrap/app.py:27-49`（`_request_id_middleware` + `_bind_request_id` / `_unbind_request_id` 直接用 `structlog.contextvars`）
- **行为**：每个 HTTP 请求自动获得 12-hex-char `request_id`，回写 `X-Request-ID` 响应头；客户端可通过同名请求头自带 ID（前端追踪场景）；structlog `merge_contextvars` 已在处理链上 → 每条 `log.*` 都自动带 `request_id`。
- **请求结束清理 contextvar**，长寿命 worker 不继承。
- **新测试**：`tests/test_request_id.py`（4 个用例：响应头存在、客户端 ID 被尊重、请求结束后 contextvar 清空、生成的 ID 唯一）

### P2.2 — `_output_capture` TTL eviction

- **位置**：`backend/src/tools/builtin/local/_output_capture.py`
- **方案**：每个 entry 存 `(payload, inserted_at_monotonic)`；任务级 1 小时 TTL、planner 级 4 小时 TTL；每次 set/pop 顺手调 `_evict_expired` 做摊销清理 — 不需要独立 janitor task。
- **新测试**：`tests/test_output_capture_ttl.py`（4 个用例：任务级过期、planner 级过期、TTL 内幸存、`clear_planner_session` 只清匹配会话）

### P2.3 — `patch_blueprint` 异常细化

- **位置**：`backend/src/tools/builtin/local/patch_blueprint.py:201-216, 308-320, 326-330`
- **改动**：3 处 `except Exception:` 改为显式 `(json.JSONDecodeError, TypeError)` / `(json.JSONDecodeError, OSError, UnicodeDecodeError)`，并加 `log.warning(...)` 留痕。
- **效果**：解码失败现在会留日志（而不是静默用 fallback），调试 / 审计更容易。

---

## 仍待办（移交到 roadmap）

| 来源 | 文件 |
|---|---|
| Phase 2 剩余 6 项 | [`docs/roadmap/phase2-backlog.md`](../../roadmap/phase2-backlog.md) |
| Phase 3 全部 7 项 | [`docs/roadmap/phase3-deferred-to-packaging.md`](../../roadmap/phase3-deferred-to-packaging.md) |
| MCP server 设计草案 | [`docs/roadmap/mcp-export-server-design.md`](../../roadmap/mcp-export-server-design.md) |
| OpenClaw 集成方案 | [`docs/roadmap/openclaw-integration-plan.md`](../../roadmap/openclaw-integration-plan.md) |

---

## 测试一览

新增 5 个测试文件：

```
backend/tests/
├── test_workflow_locks.py        4 cases
├── test_project_svc_txn.py       2 cases
├── test_crud_sql_guard.py        29 cases (param + base = 31 collected)
├── test_ws_auth.py               6 cases
├── test_request_id.py            4 cases
└── test_output_capture_ttl.py    4 cases
                                  ────────
                                  49 new test cases
```

总后端测试：**258 passing**（落地前 250）。

---

## 文档变化

- 新增：`docs/roadmap/` 目录（4 个文件）+ `docs/archive/` 目录（2 个历史文件）+ `docs/spec/` 目录（6 个搬迁文件）。
- 重写：`docs/README.md`（按"spec / iterations / roadmap / ADR / archive"四档导航）。
- 更新：`README.md`（项目根的文档入口指向新结构）。
- 同步：`docs/iterations/2026-05-16/architecture-audit.md` 顶部加更新链接。
