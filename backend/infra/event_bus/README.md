# backend/infra/event_bus/

进程内事件总线（pub/sub）。

## 文件清单

| 文件 | 职责 |
|---|---|
| `inproc_bus.py` | `InProcessEventBus`：实现 `EventBusPort.publish/subscribe` |
| `dispatcher.py` | 事件类型 → handler 注册表 + 异步分发 |
| `relay_to_ws.py` | 把 Domain Event 转成 WS 消息推到前端 |

## 设计要点

- 单进程内即可；不需要 Redis/Kafka
- handler 异步执行（asyncio）；handler 内部异常被 catch 后写日志，不影响其他 handler
- 关键事件类型见 `backend/domain/events.py` 与 plan §3.2

## WS Relay

- `relay_to_ws.py` 监听所有 `*.*` 事件（按需过滤）
- 把 Domain Event 转 WS 消息：`{ type: 'task.completed', ts, payload }`
- 前端通过 `useEvent('task.completed', handler)` 订阅

## 不做

- 不做事件持久化（不是 event-sourcing）
- 不做跨进程分发（单 sidecar 进程内）
- 不做事件回放（关闭即丢）；持久化的状态都在 SQLite + last_state.json
