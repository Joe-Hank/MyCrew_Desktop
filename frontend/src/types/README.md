# frontend/src/types/

跨页面/组件共享的 TypeScript 类型定义。

## 文件划分（按领域）

| 文件 | 内容 |
|---|---|
| `project.types.ts` | Project / ProjectState / ExecutionKind |
| `task.types.ts` | Task / TaskStatus / TaskKind / OutputSchema |
| `agent.types.ts` | Agent / Crew / Tool |
| `mcp.types.ts` | McpServer / McpTool / Transport |
| `llm.types.ts` | LlmProvider / LlmModel / LlmType |
| `inception.types.ts` | InceptionSession / InceptionMessage / TaskBlueprint |
| `events.types.ts` | WS 事件 payload 集合（与后端 §3.2 对齐） |
| `api.types.ts` | REST 请求/响应（与后端 OpenAPI 对齐） |

## 同步策略

- 后端 FastAPI 自动导出 OpenAPI JSON → `scripts/gen-types.ts` 生成 `api.types.ts`
- WS 事件 payload 从 `backend/models/schemas.py` 通过 Pydantic→TS 转换
- 这两个生成步骤纳入 `pnpm dev` 启动时的 pre-step

> 类型不手写就少出错；坚持 single source of truth = 后端 schema。
