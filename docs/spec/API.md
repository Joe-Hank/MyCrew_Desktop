# MyCrew v3 — API 参考文档

> **最后更新**：2026-05-16（PM v4 落地 + WS token 鉴权）
> 后端基于 FastAPI，运行在 `http://127.0.0.1:18321`（仅监听 loopback）。
> 所有 REST 端点前缀为 `/api/v1`，返回统一 JSON 信封。
> WebSocket 端点为 `/api/v1/ws`（带 `?token=<session-token>`）。
> 自动生成的 OpenAPI 文档可访问 `/docs`（Swagger UI）或 `/redoc`。
> 每个响应附带 `X-Request-ID` header（12 位 hex），客户端可通过同名请求头自带 id 以便跨调用追踪。

---

## 通用响应格式

### 成功
```json
{ "ok": true, "data": { ... } }
```

### 错误
```json
{ "ok": false, "error": { "code": "not_found", "message": "..." } }
```

---

## 目录

- [Health](#health)
- [Auth (WS Token)](#auth-ws-token)
- [Lifecycle](#lifecycle)
- [LLM Providers & Models](#llm-providers--models)
- [MCP Servers](#mcp-servers)
- [Projects](#projects)
- [Inception（立项）](#inception立项)
- [Workflow（工作流）](#workflow工作流)
- [PM v3/v4 Session](#pm-v3v4-session)
- [Agents](#agents)
- [Crews](#crews)
- [Tools](#tools)
- [Files](#files)
- [Config & Permissions](#config--permissions)
- [WebSocket Events](#websocket-events)

---

## Health

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/v1/health` | 健康检查，返回 `{ "status": "ok" }` |

---

## Auth (WS Token)

每次后端启动生成一个随机 session token，用于 WebSocket 握手鉴权。前端必须先调本端点拿 token，再连 WS。

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/v1/auth/ws_token` | 返回当前 session token（仅本机：`127.0.0.1` / `localhost` / `::1` / `testclient`） |

**响应**：
```json
{ "ok": true, "data": { "token": "abc_DEF-32-byte-urlsafe" } }
```

**错误码**：
- `403 forbidden` — 请求源不在 localhost 白名单
- `503 session not initialised` — 后端 lifespan 还没生成 token（极早期窗口）

**WS 握手**：
```
ws://127.0.0.1:18321/api/v1/ws?token=<token>
```
token 错或缺 → 关闭码 `4401`，前端自动 refetch token 并重连。

---

## Lifecycle

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/v1/lifecycle/state` | 获取应用运行状态（idle / running / paused / shutting_down） |
| `POST` | `/api/v1/lifecycle/pause-all` | 暂停所有运行中的工作流 |
| `POST` | `/api/v1/lifecycle/shutdown` | 优雅关闭应用（保存状态后退出） |
| `POST` | `/api/v1/lifecycle/recover` | 从异常中恢复（重载 last_state.json） |

---

## LLM Providers & Models

### Provider CRUD

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `GET` | `/api/v1/llm/providers` | 列出所有 LLM 提供商 | — |
| `GET` | `/api/v1/llm/providers/{provider_id}` | 获取单个提供商详情 | — |
| `POST` | `/api/v1/llm/providers` | 创建提供商 | `LlmProviderCreate` |
| `PUT` | `/api/v1/llm/providers/{provider_id}` | 更新提供商 | `LlmProviderUpdate` |
| `DELETE` | `/api/v1/llm/providers/{provider_id}` | 删除提供商 | — |

**LlmProviderCreate:**
```json
{
  "name": "OpenAI",
  "type": "openai",          // openai | anthropic | qwen | deepseek | ollama | custom
  "api_key_ref": "sk-xxx",
  "base_url": "https://api.openai.com/v1"  // 可选
}
```

**LlmProviderUpdate:** 同上，所有字段可选。

### Model CRUD

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `POST` | `/api/v1/llm/models` | 在指定提供商下创建模型 | `LlmModelCreate` |
| `PUT` | `/api/v1/llm/models/{model_id}` | 更新模型 | `LlmModelUpdate` |
| `DELETE` | `/api/v1/llm/models/{model_id}` | 删除模型 | — |

**LlmModelCreate:**
```json
{
  "provider_id": "uuid",
  "model_name": "gpt-4o",
  "label": "GPT-4o",           // 可选，显示名
  "max_tokens": 4096,          // 可选
  "supports_thinking": false   // 是否支持 thinking/reasoning
}
```

### 配额

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/v1/llm/quota` | 查询当前 token 用量统计 |

---

## MCP Servers

### Server CRUD

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `GET` | `/api/v1/mcp/servers` | 列出所有 MCP 服务器 | — |
| `GET` | `/api/v1/mcp/servers/{server_id}` | 获取单个服务器详情 | — |
| `POST` | `/api/v1/mcp/servers` | 创建 MCP 服务器 | `McpServerCreate` |
| `PUT` | `/api/v1/mcp/servers/{server_id}` | 更新服务器配置 | `McpServerUpdate` |
| `DELETE` | `/api/v1/mcp/servers/{server_id}` | 删除服务器 | — |

**McpServerCreate:**
```json
{
  "name": "Unity MCP",
  "transport": "stdio",        // stdio | sse | streamable-http
  "command": "npx",           // stdio 时必填
  "args": ["-y", "@anthropic/mcp-server"],
  "url": null,                // sse/streamable-http 时必填
  "env_ref": {},              // 环境变量
  "enabled": true,
  "auto_start": true,
  "timeout": 30
}
```

### 连接管理

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/api/v1/mcp/servers/{server_id}/connect` | 连接到服务器 |
| `POST` | `/api/v1/mcp/servers/{server_id}/disconnect` | 断开连接 |
| `POST` | `/api/v1/mcp/servers/{server_id}/restart` | 重启服务器 |
| `POST` | `/api/v1/mcp/refresh-all` | 刷新所有服务器连接 |
| `GET` | `/api/v1/mcp/status` | 获取所有服务器连接状态 |

### 工具调用（内部）

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `POST` | `/api/v1/mcp/internal/call` | 通过 MCP 调用工具（需权限） | `McpToolCall` |

**McpToolCall:**
```json
{
  "server_id": "uuid",
  "tool_name": "create_script",
  "arguments": { "path": "Assets/Scripts/Foo.cs", "content": "..." }
}
```

---

## Projects

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `GET` | `/api/v1/projects` | 列出所有项目 | — |
| `GET` | `/api/v1/projects/{project_id}` | 获取项目详情 | — |
| `POST` | `/api/v1/projects` | 创建项目 | `{ "name": "...", "description": "..." }` |
| `POST` | `/api/v1/projects/{project_id}/clone` | 克隆项目 | — |
| `DELETE` | `/api/v1/projects/{project_id}` | 删除项目 | — |
| `PUT` | `/api/v1/projects/{project_id}/root-path` | 设置项目根路径 | `{ "root_path": "C:/..." }` |

---

## Inception（立项）

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/v1/inceptions/sessions` | 列出所有立项会话 |
| `POST` | `/api/v1/inceptions/sessions` | 创建新会话（见下方请求体） |
| `PATCH` | `/api/v1/inceptions/sessions/{session_id}` | 重命名（仅 title 字段） |
| `DELETE` | `/api/v1/inceptions/sessions/{session_id}` | 删除会话 |
| `GET` | `/api/v1/inceptions/sessions/{session_id}` | 获取会话详情（含消息历史） |
| `POST` | `/api/v1/inceptions/sessions/{session_id}/choices` | 提交结构化选择（template_id / root_path / mode） |
| `POST` | `/api/v1/inceptions/sessions/{session_id}/messages` | 发送消息（同步，等 LLM 跑完） |
| `POST` | `/api/v1/inceptions/sessions/{session_id}/messages/stream` | 发送消息（流式，token 实时推 WS） |
| `POST` | `/api/v1/inceptions/sessions/{session_id}/index-path` | 索引项目目录 |

### SessionCreate
```json
{
  "llm_id": "prov_xxx:deepseek-chat",   // provider_id 或 provider_id:model_name
  "thinking_mode": false,
  "mode": "create",                       // create | iterate
  "parent_project_id": null,              // iterate 时必填
  "template_id": "unity_2d_pixel"        // 可选；创建时由前端 InitialTemplateChoice 预选
}
```

### SessionChoice（POST /choices）
```json
{
  "template_id": "unity_2d_pixel",       // 三选一
  "root_path": "C:/Users/.../MyGame",
  "mode": "create"
}
```

### 流式消息

走 WS 而非 SSE：POST `/messages/stream` 立即返回 `202`，token 通过 WS `inception.delta` 推送，整轮结束发 `inception.message`。

---

## Workflow（工作流）

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/api/v1/workflow/projects/{project_id}/start` | 启动项目工作流（同项目并发请求由 asyncio.Lock 串行化） |
| `POST` | `/api/v1/workflow/projects/{project_id}/pause` | 暂停工作流（Crew 任务在 step 边界软暂停） |
| `POST` | `/api/v1/workflow/projects/{project_id}/resume` | 恢复工作流 |
| `POST` | `/api/v1/workflow/projects/{project_id}/abort` | 中止工作流 |
| `POST` | `/api/v1/workflow/projects/{project_id}/tasks/{task_id}/retry` | 重试失败任务 |
| `GET` | `/api/v1/workflow/active` | 获取当前活跃工作流状态 |
| `GET` | `/api/v1/workflow/tasks/{task_id}/io?direction=in\|out` | 获取任务输入/输出数据 |
| `GET` | `/api/v1/workflow/tasks/{task_id}/sub_io?step_index=N` | **PM v4**：获取 Crew 任务的单步 IO（in / out / md） |
| `POST` | `/api/v1/workflow/tasks/{task_id}/guidance` | 任务诊断聊天（单轮无状态） |
| `PUT` | `/api/v1/workflow/tasks/{task_id}` | 更新任务配置（title / detail / agent_id / deps / position） |

### 诊断聊天请求体（PM v4 扩展）

```json
{
  "message": "用户问题",
  "step_index": 2,                 // 可选：scope 到 Crew 单步（PM v4）
  "agent_id": "agent_abc123"       // 可选：该步骤绑定的 agent，prompt 里会带上
}
```

不带 `step_index` 时 helper 读 task 级 `io_in_ref` / `io_out_ref`；带 step_index 时改读 `output/{project_id}/{task_id}/sub/<i>_*_{in,out}.{json,md}`，并在 system prompt 里追加"本次会话仅限第 N 步"约束。

### Sub-IO 响应

```json
{
  "ok": true,
  "data": {
    "step_index": 2,
    "in": { "step_index": 2, "step_role": "executor", "step_instructions": "...", "prev_step_payload": {...} },
    "out": { "step_index": 2, "step_role": "executor", "raw_text": "...", "captured": {...} },
    "raw": "# Step 3 · executor\n\n## Captured ..."
  }
}
```

Task 未创建过 sub-step（不是 Crew 任务）时 `in/out/raw` 全为 `null`，HTTP 200。

### Task 对象（含 PM v4 字段）

```json
{
  "id": "task_xxx",
  "project_id": "proj_xxx",
  "title": "Generate sprites",
  "detail": "...",
  "agent_id": "agent_xxx",
  "kind": "regular",              // regular | final_qa | setup
  "status": "running",
  "deps": ["task_yyy"],
  "output_schema": { ... },
  "io_in_ref": "F:/.../in.json",
  "io_out_ref": "F:/.../out.json",
  "position_x": 240, "position_y": 90,
  "last_activity_at": "2026-05-16T05:10:24Z",
  "validation_errors": null,
  "last_error": null,
  "last_error_kind": null,        // quota|auth|mcp|network|validation|stalled|tool|unknown
  "performer_kind": "crew",       // PM v4: agent | crew | null（legacy 用 agent_id）
  "performer_id": "crew_art"      // PM v4: agent_id 或 crew_id
}
```

---

## PM v3/v4 Session

5-phase 立项编排（完整度判定 → 主策划 → 系统策划 → 审核策划 → 项管 → 指挥员）的状态管理。

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/v1/pm/sessions/{session_id}/state` | 拉取当前 round 状态 + 草稿 |
| `POST` | `/api/v1/pm/sessions/{session_id}/save` | 把草稿落盘成真实项目（可附 `override_blueprint` 让用户编辑后保存） |
| `POST` | `/api/v1/pm/sessions/{session_id}/restart` | 从断点重跑 |
| `POST` | `/api/v1/pm/sessions/{session_id}/cancel` | 取消当前 round |

### State 响应

```json
{
  "ok": true,
  "data": {
    "status": "ready",              // idle | running_phase_<n> | ready | cancelled | failed
    "current_phase": "complete",    // completeness | concept | system_design | review | project_mgmt | agent_assignment | complete
    "phase_outputs": {
      "concept": {...}, "system_design": [...], ...
    },
    "draft_blueprint": {
      "name": "项目名",
      "execution_kind": "crew",
      "architecture_overview": "...",
      "tasks": [/* 含 performer_kind / performer_id */]
    },
    "debug_log": [/* 最近 N 条 pm.log 事件 */]
  }
}
```

### Save 请求体

```json
{ "override_blueprint": { /* 可选，用户编辑后的版本 */ } }
```

---

## Agents

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `GET` | `/api/v1/agents` | 列出所有 Agent | — |
| `GET` | `/api/v1/agents/{agent_id}` | 获取 Agent 详情 | — |
| `POST` | `/api/v1/agents` | 创建 Agent | `AgentCreate` |
| `PUT` | `/api/v1/agents/{agent_id}` | 更新 Agent | `AgentUpdate` |
| `DELETE` | `/api/v1/agents/{agent_id}` | 删除 Agent | — |

**AgentCreate:**
```json
{
  "role": "Unity 开发专家",
  "goal": "编写高质量 C# 代码",
  "backstory": "...",
  "reasoning": false,
  "max_retry": 3,
  "memory_enabled": false,
  "memory_path": null,
  "thinking_mode": false,
  "tool_ids": ["tool-uuid-1"],
  "llm_id": "model-uuid"
}
```

---

## Crews

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `GET` | `/api/v1/crews` | 列出所有 Crew | — |
| `GET` | `/api/v1/crews/{crew_id}` | 获取 Crew 详情 | — |
| `POST` | `/api/v1/crews` | 创建 Crew | `CrewCreate` |
| `PUT` | `/api/v1/crews/{crew_id}` | 更新 Crew | `CrewUpdate` |
| `DELETE` | `/api/v1/crews/{crew_id}` | 删除 Crew | — |

**CrewCreate:**
```json
{
  "name": "开发团队",
  "process": "sequential",    // sequential | hierarchical
  "agent_ids": ["agent-uuid-1", "agent-uuid-2"],

  // PM v4 字段（可选；现有 Crew 由 seed_crews 预置）
  "applicable_scenarios": "2D sprite / 概念图 / UI 图",  // Phase 5 选 Crew 时读
  "agent_sequence": "[{\"role\":\"head\",\"agent_id\":\"...\",\"step_instructions\":\"...\",\"progress_template\":\"...\"},{...},{\"role\":\"qa\",...}]"
}
```

**Crew 对象**（GET 响应）：
```json
{
  "id": "crew_art",
  "name": "美术资产组",
  "process": "sequential",
  "agent_ids": ["agent_art_director", "agent_concept_artist", "..."],
  "is_auto_generated": false,
  "promoted_at": null,
  "applicable_scenarios": "...",
  "agent_sequence": [
    { "role": "head", "agent_id": "agent_art_director", "step_instructions": "...", "progress_template": "制定 {n} 项美术规格" },
    { "role": "executor", "agent_id": "agent_concept_artist", "step_instructions": "...", "progress_template": "出参考图 ({count}/{total})" },
    { "role": "executor", "agent_id": "agent_comfy", "step_instructions": "...", "progress_template": "生成 ({count}/{total}) PNG" },
    { "role": "executor", "agent_id": "agent_ta", "step_instructions": "...", "progress_template": "导入 ({count}/{total}) sprite" },
    { "role": "qa", "agent_id": "agent_qa", "step_instructions": "...", "progress_template": "验收 {n} 个 PNG" }
  ]
}
```

---

## Tools

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `GET` | `/api/v1/tools` | 列出所有工具 | — |
| `GET` | `/api/v1/tools/{tool_id}` | 获取工具详情 | — |
| `POST` | `/api/v1/tools` | 注册工具 | `ToolCreate` |
| `DELETE` | `/api/v1/tools/{tool_id}` | 删除工具 | — |
| `POST` | `/api/v1/tools/scan` | 扫描并自动发现工具 | — |

**ToolCreate:**
```json
{
  "name": "web_search",
  "script_path": "tools/web_search.py",  // 可选
  "source": "user"                        // user | mcp | builtin
}
```

---

## Files

| Method | Path | 说明 | 请求体 | 权限 |
|--------|------|------|--------|------|
| `POST` | `/api/v1/files/index` | 索引目录文件列表 | `{ "root": "C:/project" }` | `file_read` |
| `POST` | `/api/v1/files/read` | 读取文件内容 | `{ "path": "src/main.py" }` | `file_read` |

---

## Config & Permissions

### 应用配置

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `GET` | `/api/v1/config` | 获取所有配置项 | — |
| `PUT` | `/api/v1/config` | 更新配置项 | `ConfigUpdate` |

**ConfigUpdate:**
```json
{ "key": "theme", "value": "dark" }
```

### 权限管理

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `GET` | `/api/v1/permissions` | 获取权限列表 | — |
| `PUT` | `/api/v1/permissions` | 更新权限 | `PermissionUpdate` |

**PermissionUpdate:**
```json
{ "id": "file_read", "allowed": true }
```

---

## WebSocket Events

### 连接

```
ws://127.0.0.1:18321/api/v1/ws?token=<session-token>
```

token 通过 `GET /api/v1/auth/ws_token` 获取；详见 [Auth (WS Token)](#auth-ws-token)。

### 消息格式

所有消息为 JSON，格式如下：

```json
{
  "type": "event.name",
  "ts": "2026-05-16T12:00:00Z",
  "payload": { ... }
}
```

### 服务端 → 客户端事件

#### 立项对话

| 事件 | payload | 说明 |
|---|---|---|
| `inception.delta` | `{ session_id, content }` | 流式 token |
| `inception.message` | `{ session_id, role, content, ts }` | 整轮结束的完整助手消息 |
| `inception.sub_agent_io` | `{ session_id, sub_agent, in, out }` | sub-agent 工作过程追踪 |
| `inception.workflow_created` | `{ session_id, project_id, project, blueprint }` | 草稿保存成项目后广播 |

#### PM v3/v4 编排

| 事件 | payload | 说明 |
|---|---|---|
| `pm.log` | `{ session_id, phase, level, label, status, message, ts }` | 5-phase 进度日志（前端 PMDebugLog 渲染） |

#### 项目生命周期

| 事件 | payload | 说明 |
|---|---|---|
| `project.started` | `{ project_id, ... }` | 项目启动 |
| `project.paused` | `{ project_id }` | 暂停（含 Crew step-boundary 软暂停） |
| `project.resumed` | `{ project_id }` | 恢复 |
| `project.completed` | `{ project_id }` | 全部任务完成 |
| `project.aborted` | `{ project_id, reason }` | 中止 |
| `project.progress` | `{ project_id, pct }` | 进度推送 |

#### 任务生命周期

| 事件 | payload | 说明 |
|---|---|---|
| `task.started` | `{ project_id, task_id }` | 任务开始 |
| `task.completed` | `{ project_id, task_id, output }` | 任务完成 |
| `task.failed` | `{ project_id, task_id, error, kind }` | 任务失败（kind 取自 `_classify_task_error`） |
| `task.paused` | `{ project_id, task_id }` | 任务暂停 |
| `task.blocked` | `{ project_id, task_id, reason }` | 上游失败阻塞 |
| `task.validation.failed` | `{ project_id, task_id, validation_errors }` | 输出 schema 校验失败 |
| `task.sub_step` | `{ project_id, task_id, step_index, role, agent_id, agent_role, status, error?, ts }` | **PM v4**：Crew 子步骤状态变化（status: `started` / `completed` / `failed`） |

#### Agent / MCP / Tool

| 事件 | payload | 说明 |
|---|---|---|
| `agent.output` | `{ project_id, task_id, agent_role, step, text }` | CrewAI step callback 推送的中间输出 |
| `mcp.status_changed` | `{ server_id, status }` | MCP 连接状态 |
| `mcp.tool_call` | `{ server_id, tool_name, status }` | MCP 工具调用追踪 |
| `tool.invoked` | `{ tool, status, kind?, permission_kind?, server?, mcp_tool?, duration_ms?, reason?, error? }` | 每次 builtin/MCP 工具调用的 audit 事件 |

#### 交互 / 生命周期

| 事件 | payload | 说明 |
|---|---|---|
| `prompt.request` | `{ request_id, ctx, type, options? }` | 请求用户介入（type: `choice` / `text` / `confirm`） |
| `lifecycle.recovery_prompt` | `{ projects }` | 启动时检测到上次未完成项目 |

### 客户端 → 服务端消息

| 消息类型 | 说明 | payload |
|----------|------|---------|
| `prompt.response` | 用户响应交互请求 | `{ request_id, value }` |

### 交互类型

`prompt.request` 的 `type` 字段：

| type | 说明 | 用户返回 |
|------|------|----------|
| `choice` | 选择题 | `{ value: "option_a" }` |
| `text` | 文本输入 | `{ value: "用户输入" }` |
| `confirm` | 确认/取消 | `{ value: true/false }` |

---

## 路由总览

| 模块 | 路由文件 | 端点数 |
|------|----------|--------|
| Health | `routes_health.py` | 1 |
| **Auth (WS Token)** | `routes_auth.py` | **1** (new 2026-05-16) |
| Lifecycle | `routes_lifecycle.py` | 4 |
| LLM | `routes_llm.py` | 8 |
| MCP | `routes_mcp.py` | 11 |
| Projects | `routes_project.py` | 5 |
| Inception | `routes_inception.py` | 9 |
| Workflow | `routes_workflow.py` | 10 (+ `/sub_io` + `/guidance`) |
| **PM Session** | `routes_pm.py` | **4** (PM v3/v4) |
| Agents | `routes_agent.py` | 5 |
| Crews | `routes_crew.py` | 5 |
| Tools | `routes_tool.py` | 5 |
| Files | `routes_files.py` | 2 |
| Config | `routes_config.py` | 4 |
| Settings | `routes_settings.py` | 2 |
| Templates | `routes_template.py` | 1 |
| Events | `routes_events.py` | 1 |
| Storage | `routes_storage.py` | 1 |
| WebSocket | `ws.py` | 1 (WS) |

---

*文档最后更新：2026-05-16 · PM v4 落地 + WS token 鉴权 + Phase 1/2 安全加固*
