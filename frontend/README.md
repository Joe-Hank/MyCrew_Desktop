# frontend/

React 19 + Vite 6 + TypeScript 5 前端。被 Tauri WebView 加载。

## 技术栈

- **构建**：Vite 6
- **框架**：React 19
- **样式**：Tailwind CSS 4 + Shadcn/ui（按需 copy-in）
- **路由**：React Router
- **状态管理**：
  - **服务端态** → React Query（`queries/useXxxQuery.ts`），由 REST 拉取与 WS 推送共同维护 cache
  - **UI 态** → Zustand（`stores/useXxxStore.ts`）
- **国际化**：i18next（中文优先，预留接口）

## 与后端通信

- 单条 WS 长连接（`ws://127.0.0.1:18321/ws`）+ 事件分发 hook
- REST（`http://127.0.0.1:18321/api/v1/`）通过 React Query 包装
- 端口由 Tauri 主进程通过 `invoke('get_backend_port')` 提供（启动时从 18321~18399 探测）

## 与 Tauri 主进程通信

仅用于本地能力（不转发业务）：
- `invoke('pick_file')` / `invoke('open_external', { url })` / `invoke('get_version')`
- `invoke('secret_set', { key, value })` / `invoke('secret_get', { key })`

## 子目录

- `src/pages/` 4 个页面（主页/任务/团队/设置）
- `src/components/` 组件（按页面分组 + ui kit）
- `src/queries/` React Query hooks
- `src/stores/` Zustand stores（仅 UI 态）
- `src/net/` REST + WS 客户端封装
- `src/hooks/` 通用 hook（事件分发等）
- `src/types/` TypeScript 类型定义
- `src/styles/` 全局样式 + 主题

## 关键文件（Phase 0 创建）

- `package.json` `pnpm-lock.yaml`
- `vite.config.ts` `tsconfig.json`
- `tailwind.config.ts` `postcss.config.js`
- `index.html`
- `src/main.tsx` `src/App.tsx`
