# frontend/src/hooks/

通用 React hook。

## 必备 hook

| hook | 用途 |
|---|---|
| `useEvent.ts` | 订阅 WS 事件并自动取消订阅；接受 type 字符串与 callback |
| `useTauriCommand.ts` | 包装 Tauri `invoke`，带类型推断与错误处理 |
| `useInterval.ts` | 定时刷新（配合 React Query refetchInterval） |
| `useDebounce.ts` `useThrottle.ts` | 输入防抖/节流 |
| `useDraggable.ts` | 抽屉/侧栏拖拽宽度调整（写回 `useLayoutStore`） |
| `useShortcut.ts` | 键盘快捷键 |

## 设计约定

- hook 内部不持有业务状态；只封装行为
- 业务状态走 store / query
- 副作用清理必须显式（return cleanup function）

## 示例：useEvent

```ts
useEvent('task.completed', (payload: TaskCompletedPayload) => {
  queryClient.setQueryData([...]);
  toast.success(`Task ${payload.task_id} 完成`);
});
```
