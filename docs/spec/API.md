# MyCrew v3 — API 参考文档

> 后端基于 FastAPI，运行在 `http://localhost:18321`。  
> 所有 REST 端点前缀为 `/api/v1`，返回统一 JSON 信封。  
> WebSocket 端点为 `/ws`。  
> 自动生成的 OpenAPI 文档可访问 `/docs`（Swagger UI）或 `/redoc`。

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
- [Lifecycle](#lifecycle)
- [LLM Providers & Models](#llm-providers--models)
- [MCP Servers](#mcp-servers)
- [Projects](#projects)
- [Inception（立项）](#inception立项)
- [Workflow（工作流）](#workflow工作流)
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

| Method | Path | 说明 | 请求体 |
|--------|------|------|--------|
| `GET` | `/api/v1/inceptions/sessions` | 列出所有立项会话 | — |
| `POST` | `/api/v1/inceptions/sessions` | 创建新会话 | `{ "project_id": "..." }` |
| `GET` | `/api/v1/inceptions/sessions/{session_id}` | 获取会话详情（含消息历史） | — |
| `POST` | `/api/v1/inceptions/sessions/{session_id}/messages` | 发送消息（同步） | `{ "content": "..." }` |
| `POST` | `/api/v1/inceptions/sessions/{session_id}/messages/stream` | 发送消息（SSE 流式） | `{ "content": "..." }` |
| `POST` | `/api/v1/inceptions/sessions/{session_id}/index` | 索引项目文件 | — |
| `POST` | `/api/v1/inceptions/sessions/{session_id}/finalize` | 确认蓝图并创建项目 | `{ "blueprint": { ... } }` |

### SSE 流式响应格式
```
data: {"type": "token", "content": "..."}
data: {"type": "done", "content": "完整回复"}
```

---

## Workflow（工作流）

| Method | Path | 说明 |
|--------|------|------|
| `POST` | `/api/v1/workflow/projects/{project_id}/start` | 启动项目工作流 |
| `POST` | `/api/v1/workflow/projects/{project_id}/pause` | 暂停工作流 |
| `POST` | `/api/v1/workflow/projects/{project_id}/resume` | 恢复工作流 |
| `POST` | `/api/v1/workflow/projects/{project_id}/abort` | 中止工作流 |
| `POST` | `/api/v1/workflow/projects/{project_id}/tasks/{task_id}/retry` | 重试失败任务 |
| `GET` | `/api/v1/workflow/active` | 获取当前活跃工作流状态 |
| `GET` | `/api/v1/workflow/tasks/{task_id}/io` | 获取任务输入/输出数据 |
| `PUT` | `/api/v1/workflow/tasks/{task_id}` | 更新任务配置 |

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
  "agent_ids": ["agent-uuid-1", "agent-uuid-2"]
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
ws://localhost:18321/ws
```

### 消息格式

所有消息为 JSON，格式如下：

```json
{
  "type": "event.name",
  "ts": "2026-05-10T12:00:00Z",
  "payload": { ... }
}
```

### 服务端 → 客户端事件

| 事件类型 | 说明 | payload |
|----------|------|---------|
| `task.state_changed` | 任务状态变更 | `{ project_id, task_id, old_state, new_state }` |
| `task.output` | 任务输出（实时流） | `{ project_id, task_id, text }` |
| `workflow.started` | 工作流启动 | `{ project_id }` |
| `workflow.completed` | 工作流完成 | `{ project_id, summary }` |
| `workflow.failed` | 工作流失败 | `{ project_id, error }` |
| `mcp.status` | MCP 服务器状态变更 | `{ server_id, status }` |
| `prompt.request` | 请求用户交互输入 | `{ request_id, project_id, task_id, title, type, options? }` |
| `inception.token` | 立项对话流式 token | `{ session_id, content }` |

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

共 **75** 个注册路由（含 OpenAPI/docs 的 4 个内置路由）。

| 模块 | 路由文件 | 端点数 |
|------|----------|--------|
| Health | `routes_health.py` | 1 |
| Lifecycle | `routes_lifecycle.py` | 4 |
| LLM | `routes_llm.py` | 8 |
| MCP | `routes_mcp.py` | 11 |
| Projects | `routes_project.py` | 5 |
| Inception | `routes_inception.py` | 7 |
| Workflow | `routes_workflow.py` | 8 |
| Agents | `routes_agent.py` | 5 |
| Crews | `routes_crew.py` | 5 |
| Tools | `routes_tool.py` | 5 |
| Files | `routes_files.py` | 2 |
| Config | `routes_config.py` | 4 |
| WebSocket | `ws.py` | 1 (WS) |

---

*文档生成时间：2026-05-11 · 基于 FastAPI 自动路由扫描*
