# backend/infra/interaction/

`InteractionPort` 的实现：通过 WebSocket 与前端双向交互，替代 CrewAI 默认的 `input()` 调用。

## 文件清单

| 文件 | 职责 |
|---|---|
| `ws_interaction.py` | `WsInteraction` 类，实现 `prompt_choice` / `prompt_text` / `prompt_confirm` |
| `pending_prompts.py` | 在内存中维护 `request_id → asyncio.Future` 映射 |

## 工作流

```
1. service / domain 调用 InteractionPort.prompt_xxx(...)
2. WsInteraction 生成 request_id，建一个 Future，发 WS 事件 prompt.request
3. 前端弹窗，用户选择 → 发 prompt.response { request_id, value }
4. WS Hub 路由到 WsInteraction.resolve(request_id, value) → set Future
5. service / domain 收到结果继续运行
```

## 兜底

- 超时（默认 5min）：Future 自动 cancel，service 收到异常 → Task 标 failed
- 断连：所有 pending Future 标 cancelled；后端在 prompt_audit 表记录"断连"原因
- 重启恢复：last_state.json 不持久化 pending Prompt（用户必须重新介入）

## 替代 input() 的语义保证

- CrewAI 内部如果还有 `input()` 调用，必须 monkey-patch 或在调用上下文用 contextvar 传 `WsInteraction` 实例进去
- 任何走真实 stdin 的调用都视为 bug
