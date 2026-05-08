# frontend/src/net/

网络层：REST 客户端 + WebSocket 单例。

## 文件清单

| 文件 | 职责 |
|---|---|
| `api.ts` | REST 客户端（基于 fetch 或 axios），统一响应包装 `{ ok, data, error }`，全局错误拦截 |
| `ws.ts` | 单例 WebSocket 连接，重连退避，事件分发到 `useEvent` hook |
| `types.ts` | 网络层共享类型（请求/响应/事件 payload） |

## 基址获取

- 启动时调 `invoke('get_backend_port')` 拿到后端端口（18321~18399 探测后的实际值）
- REST 基址：`http://127.0.0.1:{port}/api/v1/`
- WS 端点：`ws://127.0.0.1:{port}/ws`

## REST 响应约定

```ts
type ApiResponse<T> =
  | { ok: true; data: T }
  | { ok: false; error: { code: string; message: string } };
```

## WS 消息约定

```ts
type WsMessage = {
  type: string;          // e.g. 'task.completed'
  ts: string;            // ISO8601
  payload: object;
};
```

## 重连策略

- 指数退避（1s → 2s → 4s → 8s → 16s → 30s 上限）
- 失败超 5 次后弹"后端连接异常"Toast，并提示用户检查 sidecar 健康
- 连接成功后自动恢复订阅
