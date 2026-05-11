# MyCrew v3 实施进度 — 2026-05-09

## 已完成 Phase

| Phase | 说明 | 状态 |
|-------|------|------|
| 0-2 | 骨架 + 配置/凭据 + 启动加载 | ✅ committed |
| 3 | MCP 连接池 + 首批包装 Tool | ✅ committed |
| 4 | Harness 领域核心（状态机/DAG/事件总线/交互端口） | ✅ committed |
| 5 | 主页 + 立项全流程（ProjectGrid/InceptionDrawer/会话历史/蓝图编辑） | ✅ committed |
| 6 | 任务页（DAG 蓝图/ProjectHeader/TaskNode/IO 查看器/Agent 对话） | ✅ committed |
| 7 | 团队页（Agent/Crew/Tool 三 Tab + EditorDrawer） | ✅ committed |
| 8 | 设置页完善 + 权限拦截 + 视觉对齐 | ✅ committed |
| 9 | 打磨与打包（主题/错误边界/PyInstaller/Tauri sidecar） | ✅ committed |
| 10 | Figma 原型对齐（设置页/团队页/主页 → 药丸Tab+表格+底部状态栏） | ✅ committed |

## Phase 9 新增/修改文件

- `frontend/src/stores/useThemeStore.ts` — Zustand 持久化主题 store（light/dark/system 三态循环）
- `frontend/src/components/layout/ErrorBoundary.tsx` — React 错误边界，带重试按钮
- `frontend/src/components/layout/AppShell.tsx` — 集成 ErrorBoundary + 主题初始化
- `frontend/src/components/layout/Sidebar.tsx` — 增加 ThemeToggle 组件
- `backend/mycrew_backend.spec` — PyInstaller 打包规格（单文件 exe）
- `src-tauri/tauri.conf.json` — 增加 `externalBin` sidecar 配置
- `scripts/build.py` — 一键构建脚本（PyInstaller → copy binary → cargo tauri build）

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
- 所有 Phase 0-9 已 commit 并 push 到 `origin/phase-6-7-8` 分支

## 所有 Phase 完成 ✅

plan.md 中定义的 Phase 0-9 全部实现完毕。

### 收尾工作（已完成）
- ✅ 合并 `phase-6-7-8` 分支到 `main`（fast-forward）
- ✅ 文档补全：`docs/BUILD.md`（构建指南）+ `docs/USER_GUIDE.md`（用户指南）
- ✅ E2E 测试配置：`frontend/playwright.config.ts` + `frontend/e2e/smoke.spec.ts`（6 个冒烟用例）
- ✅ package.json 添加 `e2e` / `e2e:install` 脚本

### 待 push（网络恢复后）
本地 main 有 2 个 commit 待 push：
- `ddc18b0` docs: add BUILD.md and USER_GUIDE.md
- `3ae0774` test: add Playwright E2E smoke tests config

### 运行 E2E 测试
```bash
cd frontend
pnpm add -D @playwright/test
pnpm e2e:install
pnpm e2e
```

### 剩余可选工作
- 实际 PyInstaller 打包验证（需要完整 Python 环境 + 依赖安装）
- cargo tauri build 出安装包

---

## Phase 11 — LLM Gateway + Lifecycle API（2026-05-10，Claude Sonnet 4）

### 完成内容

| 模块 | 说明 | 状态 |
|------|------|------|
| LLM Gateway | `backend/infra/llm/` — base/openai_adapter/anthropic_adapter/registry/gateway | ✅ |
| LLM Service | `backend/services/llm_svc.py` — 统一 LLM 调用入口 | ✅ |
| Inception 接入真实 LLM | `backend/services/inception_svc.py` — 调用 llm_svc 生成蓝图 | ✅ |
| Workflow 结构化提取 | `backend/services/workflow_svc.py` — JSON 提取 + schema 校验 | ✅ |
| Lifecycle Routes | `backend/api/routes_lifecycle.py` — state/pause-all/shutdown/recover | ✅ |
| Inception Streaming | `backend/api/routes_inception.py` — SSE streaming endpoint | ✅ |
| PyInstaller Spec 修复 | 入口点改为 `bootstrap/main.py`，补全 hidden imports | ✅ |
| App 创建验证 | `backend/tests/test_app_create.py` — 75 routes, 5 critical endpoints OK | ✅ |

### 新增/修改文件

#### 后端 — LLM 基础设施
- `backend/infra/llm/__init__.py` — 包导出
- `backend/infra/llm/base.py` — `LlmAdapter` 抽象基类（chat/stream_chat/extract_json）
- `backend/infra/llm/openai_adapter.py` — OpenAI/兼容 API 适配器（httpx 异步）
- `backend/infra/llm/anthropic_adapter.py` — Anthropic Claude 适配器
- `backend/infra/llm/registry.py` — 适配器注册表（按 provider_id 管理实例）
- `backend/infra/llm/gateway.py` — 统一网关（自动路由到正确 adapter）

#### 后端 — 服务层
- `backend/services/llm_svc.py` — LLM 服务封装（chat/stream/extract）
- `backend/services/inception_svc.py` — 重写：接入 llm_svc 真实调用
- `backend/services/workflow_svc.py` — 重写：结构化输出提取 + jsonschema 校验

#### 后端 — API
- `backend/api/routes_lifecycle.py` — Lifecycle 端点（GET state / POST pause-all / POST shutdown / POST recover）
- `backend/api/routes_inception.py` — 增加 `/sessions/{id}/messages/stream` SSE 端点

#### 后端 — 打包
- `backend/mycrew_backend.spec` — 修复入口点（app.py → main.py），添加所有应用模块到 hiddenimports

#### 后端 — 测试
- `backend/tests/test_llm_imports.py` — LLM adapter 导入 + 实例化测试（7 tests passed）
- `backend/tests/test_service_imports.py` — 服务层导入验证（6 tests passed）
- `backend/tests/test_app_create.py` — FastAPI app 创建集成测试

#### 依赖
- `backend/pyproject.toml` — 添加 `tenacity` 依赖（LLM 重试）

### 验证结果
- ✅ pytest 7/7 passed（LLM adapter 单元测试）
- ✅ 服务层导入 6/6 OK
- ✅ FastAPI app 创建成功：**75 个路由**，71 个 API 路由
- ✅ 关键端点验证通过：health / llm/providers / inceptions/sessions / workflow/active / lifecycle/state

### Git Commits（本地，待 push）
- `ea127a4` feat: implement LLM gateway with OpenAI/Anthropic adapters, wire inception and workflow services
- `ee9ecd2` fix: pyinstaller spec entry point + app creation test (75 routes, all critical endpoints verified)

### 当前统计
- 后端 **75 API routes**（从 65+ 增长到 75）
- LLM 支持：OpenAI + Anthropic 双 adapter
- 所有服务层模块均可正常导入和实例化
