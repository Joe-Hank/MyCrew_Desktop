# frontend/src/stores/

Zustand store，**仅用于 UI 态**（抽屉开关 / 选中项 / 拖拽态 / 主题 / DAG 编辑暂存等）。

## 命名规范

- 一个 store 一个文件：`useXxxStore.ts`

## 必备 store 清单

| store | 用途 |
|---|---|
| `useUIStore` | 全局 UI 开关：inceptionDrawerOpen / logDrawerOpen / activeLogTab / theme |
| `useLayoutStore` | 抽屉宽度记忆（黄金分割可调）/ 侧栏折叠 |
| `useTaskUIStore` | DAG 视图缩放/平移、当前选中节点、Blueprint 编辑暂存 |
| `useInceptionDraftStore` | 立项对话本地草稿（离线时缓冲，上线后冲到后端） |
| `useToastStore` | 全局通知队列 |

## 红线

- **禁止**把服务端态（项目列表/任务/MCP）放进 Zustand
- **禁止**直接 fetch 后写进 Zustand；服务端态走 React Query
- **禁止**跨 store 互相调用（容易循环）；用事件总线（`useEvent`）协调
