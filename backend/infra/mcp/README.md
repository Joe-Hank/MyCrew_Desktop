# backend/infra/mcp/

MCP Port 的 Adapter 实现。

## 文件清单（Phase 3 落地）

| 文件 | 职责 |
|---|---|
| `stdio_client.py` | stdio MCP 客户端：subprocess spawn、JSON-RPC over stdin/stdout、读取 schema |
| `http_client.py` | HTTP MCP 客户端：标准 MCP HTTP/SSE 协议 |
| `pool.py` | MCP 服务器池：管理多个 server 的生命周期（启动/停止/心跳/重连）；同步 `discovered_tools` 到 DB |
| `proxy.py` | 实现 `MCPPort`：路由 `call(server_id, tool_name, args)` 到具体 server |
| `health.py` | 心跳与连接状态：30s 探测、状态变化广播 `mcp.connected/disconnected` |

## 关键约束

- 每个 MCP 独立子进程；单 server 崩溃不影响其他
- 关闭信号传播：先发 stdio 关闭 → 等 5s → 强杀；启动时再次扫描端口/PID 清理僵尸
- `discovered_tools` 仅作元数据展示用；**Agent 不直接调 raw MCP 工具**（要走 src/tools/builtin/mcp_<server>/ 的手写包装）

## 与 src/tools/builtin/mcp_<server>/ 的关系

```
Agent 调用 BaseTool 包装                ← src/tools/builtin/mcp_<server>/
   ↓ (Pydantic 校验入参)
mcp_pool.call(server_id, tool_name, validated_args)   ← 这里
   ↓
infra/mcp/proxy.py → stdio_client / http_client
   ↓
真实 MCP 服务器
```

## 严控策略

- 只有"已包装"的 MCP 工具对 Agent 可见（agent_svc 注入到 CrewAI Agent 的 tools 列表）
- 未包装的工具列在团队页 Tools tab 灰色文字 + "生成包装骨架"按钮
