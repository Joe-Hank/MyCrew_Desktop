# OpenClaw 集成方案

> 设定：假定 OpenClaw 是要把 MyCrew 当作 MCP server 调用的外部多 Agent 框架（如果实际语义不同，请先确认）。
> 优先级：D 级（不在 Phase 1/2 紧急范围；本文件记录设计 + 现在该做的准备工作）。
> 当前状态：**设计完成；准备工作清单已列；具体实现待用户触发**。

---

## 当前应执行的准备工作（**本轮要做的事**）

这一节列出**不实现 OpenClaw 集成也应该现在做的事** —— 做完之后未来要拉起集成是"接一根线"的工作量。

### ✅ 准备工作 1：审计 actor 字段已能区分调用源（已就绪）

**事实**：`events.actor` 列存在，但目前所有 write path 都填 `"system"` / `"user"`。

**该做**：本轮**不动代码**，但**在评审里立规则** —— 未来从外部调用 MyCrew 必须用 `actor="openclaw:<session_id>"` 这种唯一可识别格式。

**记录在**：[mcp-export-server-design.md](./mcp-export-server-design.md#准备工作-1)（共享同一前置条件）。

### ✅ 准备工作 2：`permission_kind` 预留 `external_agent_call`

**该做**：下次 migration 时 seed 一条 `(kind='external_agent_call', pattern='*', allowed=0)`，默认禁用。

**记录在**：[mcp-export-server-design.md](./mcp-export-server-design.md#准备工作-2)（共享同一前置条件）。

### ✅ 准备工作 3：双向集成的方向决策（**等用户确认**）

OpenClaw 集成有**两个方向**：

| 方向 | 含义 | 实施依赖 |
|---|---|---|
| **A. OpenClaw 调 MyCrew**（MyCrew 是 server） | OpenClaw 通过 MCP client 拉起 MyCrew 工具 | 需要先实现 [mycrew-export-mcp](./mcp-export-server-design.md) |
| **B. MyCrew 调 OpenClaw**（OpenClaw 是 server） | MyCrew 把 OpenClaw 当作一个新 MCP server 接入 | 走现有 MCP pool 注册路径（无新基础设施） |
| **C. 双向**（peer-to-peer） | 互相暴露工具 | A + B |

**用户决策点**：**首选哪个方向？** 这决定了实施的起点。

- 选 A：先做 export server，OpenClaw 集成是 export server 的第一个客户端。
- 选 B：写一个 OpenClaw MCP wrapper（参考现有 `backend/src/tools/builtin/mcp_blender/`），seed 一个 `agent_openclaw_*` agent 挂这些工具。
- 选 C：两件事都做，按 A → B 顺序拉。

---

## 设计 — 假设走方向 A（OpenClaw 调 MyCrew）

### 数据流

```
┌─────────────────────────────┐
│ OpenClaw 进程               │
│ ┌────────────────────────┐  │
│ │ MCP Client             │  │
│ └────────┬───────────────┘  │
└──────────┼──────────────────┘
           │ stdio JSON-RPC
           ↓
┌──────────────────────────────────────────────┐
│ mycrew-export-mcp 子进程                     │
│ ┌────────────────────────────────────────┐   │
│ │ MCP Server                             │   │
│ │   tools = [list_projects, ...]         │   │
│ │   resources = [...]                    │   │
│ └────────┬───────────────────────────────┘   │
└──────────┼───────────────────────────────────┘
           │ HTTP (localhost)
           ↓
┌──────────────────────────────────────────────┐
│ MyCrew 主后端 (FastAPI)                      │
│   permission_guard + WorkflowService         │
│   + asyncio.Lock + compensating txn          │
└──────────────────────────────────────────────┘
```

### 接入步骤（**仅清单，不动代码**）

1. **完成 [mycrew-export-mcp](./mcp-export-server-design.md) 的 Phase A**（list_projects + query_events 两个工具）。
2. **OpenClaw 侧**：写 MCP client 配置，指向 `mycrew-export-mcp` 子进程。
3. **MyCrew 侧的运维操作**：
   - 用户在设置页开 `external_agent_call` 权限开关。
   - 启动后端时 `MYCREW_EXPORT_MCP=1`。
4. **端到端验收**：
   - OpenClaw 调 `list_projects` → 返回 MyCrew 当前所有项目。
   - OpenClaw 调被禁的 `invoke_crew` → 应被 permission 拦截，事件落入 `events` 表 `actor="openclaw:<sid>"`。
5. **审计 watchdog**：每 5 分钟统计 `actor LIKE 'openclaw:%'` 的调用频次，超 1k/h 告警（默认阈值）。

---

## 设计 — 假设走方向 B（MyCrew 调 OpenClaw）

### 数据流

```
┌──────────────────────────────────────────────┐
│ MyCrew 主后端                                │
│ ┌────────────────────────────┐               │
│ │ infra.mcp.pool             │               │
│ │   server_id="mcp_openclaw" │               │
│ └────┬───────────────────────┘               │
└──────┼───────────────────────────────────────┘
       │ stdio
       ↓
┌──────────────────────────────────────────────┐
│ OpenClaw 进程（暴露 MCP server 接口）       │
│   tools = [run_agent, list_tools, ...]       │
└──────────────────────────────────────────────┘
```

### 接入步骤（**仅清单**）

1. **DB seed**：`mcp_servers` 表插入一条 OpenClaw 行（stdio + command）：
   ```sql
   INSERT INTO mcp_servers (id, name, transport, command, args, auto_start, timeout)
   VALUES ('mcp_openclaw', 'OpenClaw', 'stdio', 'python', '["-m","openclaw.mcp"]', 1, 30);
   ```
2. **Wrapper 文件**（参考 `backend/src/tools/builtin/mcp_blender/execute_code.py`）：
   ```
   backend/src/tools/builtin/mcp_openclaw/
   ├── __init__.py
   ├── tools.py              # 每个 OpenClaw tool 一个 BaseTool 子类
   └── README.md             # 写清 OpenClaw 接口约定
   ```
3. **注册到 crewai_runner**：`_load_builtin_tools` 的 `static_registry` 加 mapping。
4. **seed_builtin_tools** 加新工具名（5-10 条）。
5. **seed 一个 agent**：role `"OpenClaw Agent"`，挂这些工具，留给 Phase 5 调度。

### 安全要点

- OpenClaw 进程**不在沙箱里**，跟其他 MCP server 一样。如果 OpenClaw 本身执行任意代码（如 OpenClaw 是个 LLM agent runtime），那这是一个**权限提升路径** —— 必须给它的工具加 `permission_kind`（cmd_exec / file_write 等），让用户的权限矩阵开关能拦住。
- 工具 wrapper 必须继承 `GuardedMCPTool`（`backend/src/tools/builtin/_base.py`），自动获得审计 + 权限检查。

---

## 工作量估算

### 走方向 A
| 阶段 | 工作量 |
|---|---|
| mycrew-export-mcp Phase A | 2 天（见 MCP 设计文档） |
| OpenClaw 侧适配（client 配置） | 0.5 天（如 OpenClaw 有现成 MCP client） |
| 端到端测试 | 0.5 天 |
| **小计** | **3 天** |

### 走方向 B
| 阶段 | 工作量 |
|---|---|
| OpenClaw MCP wrapper（假设 5 个工具） | 1.5 天 |
| seed + 注册 + 一个测试 agent | 0.5 天 |
| 端到端测试（OpenClaw 通过 MyCrew agent 运行） | 1 天 |
| **小计** | **3 天** |

### 走方向 C
两者并行可压缩到 4-5 天（共享准备工作）。

---

## 与本轮已落地工作的关系

OpenClaw 集成**不需要**等本轮的 P1/P2 修复 —— 那些修复就是为了让外部调用安全。具体关联：

| 本轮修复 | 对 OpenClaw 集成的意义 |
|---|---|
| P1.2 WorkflowService asyncio.Lock | OpenClaw 并发触发同一个 MyCrew 项目时不会产生重复 harness |
| P1.3 create_project_with_tasks 补偿事务 | OpenClaw 调 create_project 中途断网不会留半成品 |
| P1.4 crud.py SQL 守卫 | OpenClaw 传 query_events 参数也走同一层防御 |
| P1.5 WS token auth | OpenClaw 不能伪造 WS 事件骗 InteractionPort 自动批准 |
| P2.1 request_id middleware | OpenClaw 调用链每一步都能追踪 |
| P2.2 capture TTL | OpenClaw 中途崩溃留下的 emit_output 不会无限堆积 |

→ **本轮把 OpenClaw 集成的"基础设施债"全清了**。下次只要走"接一根线"，地基已经好。

---

## 决策树（**用户参考**）

```
是否要接 OpenClaw？
├─ 是 → 选方向？
│   ├─ A（OpenClaw 调我） → 先做 mycrew-export-mcp Phase A
│   ├─ B（我调 OpenClaw） → 先做 mcp_openclaw wrapper
│   └─ C（双向） → A + B 都做
└─ 否 → 本文件保持归档，触发时再回来读
```

**触发条件**：用户明确说"我要接 OpenClaw"。在此之前**不做任何 OpenClaw 专属编码**，但本轮已做的安全/可靠性加固足以让未来接入零基础设施债。
