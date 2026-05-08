# frontend/src/

React 应用源码。

## 入口

- `main.tsx` — React 渲染根
- `App.tsx` — 路由 + 全局 Provider（QueryClient / Theme / I18n / 错误边界）

## 目录划分（强约束）

| 目录 | 用途 | 命名规范 |
|---|---|---|
| `pages/` | 4 个顶层页面 | `XxxPage.tsx` |
| `components/` | 组件库；按页面分组 + 通用 ui | `XxxComponent.tsx` |
| `queries/` | React Query hook，**服务端态** | `useXxxQuery.ts` |
| `stores/` | Zustand store，**UI 态** | `useXxxStore.ts` |
| `net/` | REST 客户端 + WS 单例 | `api.ts` `ws.ts` |
| `hooks/` | 通用 hook | `useXxx.ts` |
| `types/` | 共享 TypeScript 类型 | `xxx.types.ts` |
| `styles/` | 全局样式 + 主题 | `globals.css` `theme.ts` |

## 关键约束

- **不要把服务端态放到 Zustand**（缓存一致性会乱）
- **不要把 UI 态放到 React Query**（无 server roundtrip）
- 跨页面共享的状态：UI → Zustand global slice；数据 → React Query 配 `staleTime` 与 `cacheTime`
- 所有外部调用（REST/WS/Tauri invoke）都封装到 `net/` 或 `hooks/` 下，组件层只调 hook 不直接 fetch
