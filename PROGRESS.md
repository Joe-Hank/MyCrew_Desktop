# MyCrew v3 实施进度 — 2026-05-09

## 已完成 Phase

| Phase | 说明 | 状态 |
|-------|------|------|
| 0-2 | 骨架 + 配置/凭据 + 启动加载 | ✅ committed |
| 3 | MCP 连接池 + 首批包装 Tool | ✅ committed |
| 4 | Harness 领域核心（状态机/DAG/事件总线/交互端口） | ✅ committed |
| 5 | 主页 + 立项全流程（ProjectGrid/InceptionDrawer/会话历史/蓝图编辑） | ✅ committed |
| 6 | 任务页（DAG 蓝图/ProjectHeader/TaskNode/IO 查看器/Agent 对话） | ✅ **未 commit** |
| 7 | 团队页（Agent/Crew/Tool 三 Tab + EditorDrawer） | ✅ **未 commit** |
| 8 | 设置页完善 + 权限拦截 + 视觉对齐 | ✅ **未 commit** |

## Phase 8 新增/修改文件

### 后端
- `backend/services/permission_guard.py` — 权限拦截模块：`require_permission(kind)` + `check_tool_permissions(tool_name, args)` 启发式检查
- `backend/api/routes_mcp.py` — `/internal/call` 端点增加权限检查（调用 `check_tool_permissions`）
- `backend/api/routes_files.py` — `/files/index` 和 `/files/read` 增加 `file_read` 权限检查

### 前端
- `frontend/src/components/settings/EditorDrawer.tsx` — **新增**：LLM 编辑表单（名称/类型/API Key/Base URL + 内嵌模型列表编辑器）+ MCP 编辑表单（名称/协议/命令/参数/环境变量/超时/启用/自动启动）
- `frontend/src/components/settings/DefaultLlmSelector.tsx` — **新增**：双默认 LLM 选择器（立项默认 + Agent 默认），存储到 `app_settings`
- `frontend/src/components/settings/PermissionMatrix.tsx` — 重写：增加图标、描述文字、提示信息、无障碍标签
- `frontend/src/components/settings/LlmList.tsx` — 重写：显示类型标签、模型数量、Base URL
- `frontend/src/components/settings/McpList.tsx` — 重写：显示协议标签、启用状态、命令/URL 信息
- `frontend/src/pages/SettingsPage.tsx` — 重写：集成 EditorDrawer + DefaultLlmSelector + 新建按钮
- `frontend/src/queries/useLlmQuery.ts` — 增加类型定义（LlmProvider/LlmModel）+ LLM_TYPES 常量 + Model CRUD hooks
- `frontend/src/components/layout/Sidebar.tsx` — 视觉对齐：活跃态蓝色高亮、rounded-lg、min-width
- `frontend/src/pages/TeamPage.tsx` — 视觉对齐：统一 Tab 样式（与设置页一致）+ 新建按钮 + 数量徽标

### 视觉对齐要点
- 所有页面 Tab 栏统一样式：`border-b-2 border-blue-500` 活跃态 + 数量徽标
- 列表项统一 hover 效果：`hover:bg-zinc-50 dark:hover:bg-zinc-800/50`
- 编辑器抽屉统一宽度 `w-[320px]`
- Sidebar 活跃项改为蓝色系（`bg-blue-50 text-blue-600`）
- 空状态统一使用 emoji + 提示文案
- Tauri 窗口已配置 minWidth=960, minHeight=600 保证响应式

## 当前统计
- 后端 65+ API routes
- 前端 tsc 零错误
- Phase 6-8 代码尚未 git commit

## 下一步：Phase 9

**Phase 9 — 打磨与打包**
- 主题切换、版本号、空状态、loading、错误兜底
- PyInstaller 后端打包
- Tauri build 前端+后端集成
- 自动更新 + 安装流程

### 注意事项
- 所有 Phase 6-8 变更需要先 commit 再开始 Phase 9
