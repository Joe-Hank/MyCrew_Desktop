# frontend/src/components/layout/

应用骨架（所有页面共享）。

## 组件清单

| 组件 | 职责 |
|---|---|
| `AppShell.tsx` | 顶层布局：左侧栏 + 内容区 + 底部日志栏 |
| `Sidebar.tsx` | 固定宽度（约 200px）：Logo / 4 页面入口 / 主题切换（日夜）/ 版本号 |
| `LogDrawer.tsx` | 默认收起仅显后端最后一行；展开后多终端 Tab（每 MCP 一 tab + 应用日志 tab + Agent 输出 tab）；右上角"收起" |

## 设计要点

- AppShell 渲染一次，4 页路由切换只换中间内容
- LogDrawer 状态（收起/展开 + 当前 Tab）走 Zustand `useLayoutStore`
- 主题切换走 CSS 变量；初始值从 `app_settings.theme` 读，变更通过 Tauri invoke 持久化
