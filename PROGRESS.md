# MyCrew v3 实施进度 — 2026-05-12

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
| 11 | LLM Gateway + Lifecycle API（OpenAI/Anthropic adapter, SSE streaming） | ✅ committed |
| 12 | Port 层补全 + 状态机 bug 修复 + 测试覆盖增强 | ✅ committed |
| 13 | 测试补强（36→140 pytest）+ log_svc 桩填充 + 代码审查报告 | ✅ committed |
| 14 | Figma UI 全面对齐（Phase A-F：tokens/sidebar/home/task/team/settings/inception） | ✅ committed |
| 15 | v2 配置全数导入（6 LLM + 15 model + 7 MCP + 4 tool + 17 agent + 8 crew） | ✅ committed |
| 16 | MVP 收尾（Wave 1-4：quick wins + MCP 拦截 + CrewAI + InteractionPort + 路径/迭代 + dark mode + experience_repo + heartbeat） | 🔄 pending commit |

---

## Phase 16 — MVP 收尾（2026-05-12）

按"关键 → 体验 → 选配"优先级 + 依赖关系完成剩余 9 项。

### Wave 1 — Quick wins
- `routes_lifecycle.py` `active_tasks` 真实计数（从 0 硬编码改为 SQL 聚合）
- 新增迁移 `0002_indexes.py`：tasks(project_id) / tasks(status) / tasks(project_id,status) 复合索引 + inception_messages(session_id) + llm_models(provider_id) + projects(state)
- `log_svc` 改用 SQLite `logs` 表持久化 + 保留内存环形缓冲作为 tail cache
- 新增 `diagnostic_svc.py` + `POST /lifecycle/diagnostic-bundle`（ZIP 含 logs + 脱敏 configs + system info）
- `llm_gateway.chat()` 加 `llm.call_started/call_finished/call_failed` WS 事件广播

### Wave 2 — 架构补完
- **MCP 工具拦截 wire-up**：新增 `_base.py::GuardedMCPTool` 基类；4 个 BaseTool 改为继承基类 + 声明 `permission_kind`；skeleton_generator 模板同步更新
- **CrewAI 实际接入**：新增 `services/crewai_runner.py`，真实构建 Agent/Task/Crew + LiteLLM；`workflow_svc._run_agent` 优先走 CrewAI，失败时降级到 LlmGateway 直调
- **InteractionPort 接线**：前端新增 `layout/PromptModal.tsx`，全局监听 `prompt.request` 渲染 choice/text/confirm 三种 UI，应答发回 `prompt.response`

### Wave 3 — UI 占位补完
- 主页卡片"路径"按钮：嵌入式输入 → `useUpdateRootPath`
- 主页卡片"迭代"按钮：终态项目可点击 → `useCloneProject`
- **深色模式**：用 `:root.dark` 重映射 Tailwind `--color-white`/`--color-zinc-*` token，硬编码 `bg-white/zinc-*` 自动切换，免逐文件改 `dark:` 变体

### Wave 4 — 选配
- **experience_repo SQLite**：迁移 `0003_experiences.py` + `infra/experience/sqlite_experience_repo.py`，填掉 plan §6 最后一个 NotImplementedError 桩
- **MCP heartbeat 加固**：`_heartbeat_loop` 加外层 try/except，单次故障不再静默杀死 task

### 验证
- ✅ pytest **150 passed**（140 → 150，新增 test_experience_repo.py × 10）
- ✅ `npx tsc --noEmit` 零错误
- ✅ `npx vite build` 778ms / 139 modules

---

## Phase 14 — Figma UI 全面对齐（2026-05-12）

### 完成内容

| 子阶段 | 内容 |
|--------|------|
| A | 全局 token 系统（CSS `@theme` + 品牌色 `#0c8ce9`）+ 侧边栏窄化（200→110px）+ 2 态主题切换 + 日志栏简化 |
| B | 主页：2 列 → **4 列卡片网格** + **卡内嵌任务条** + **MCP/Token 双状态栏** + chevron 分页 |
| C | 任务页：**选中任务 header** + **节点 5 图标操作栏** + **贝塞尔曲线连接** |
| D | 团队页：Agents/Crews/Tools 表 + 行 ⋯ 菜单 + **左侧抽屉编辑器** |
| E | 设置页：LLM/MCP/权限表 + 同款左侧抽屉 |
| F | 立项流程：**全屏覆盖** + 顶部 LLM/模型/思考切换 + 左聊天右蓝图 + **底部确认按钮** |

### 新增共享组件

- `components/common/PillTabs.tsx` — 药丸式 Tab 组件（团队/设置共用）
- `components/common/RowActionsMenu.tsx` — ⋯ 行操作菜单
- `components/common/SideDrawer.tsx` — 左侧抽屉 + `DrawerFooter` + `FormField` + `inputCls`

### 删除已废弃文件（14 个）

- `task/ProjectHeader.tsx`、`home/McpStatusBar.tsx`
- `team/{AgentList,CrewList,ToolList,EditorDrawer}.tsx`
- `settings/{LlmList,McpList,PermissionMatrix,LlmEditOverlay,McpEditOverlay,EditorDrawer,DefaultLlmSelector}.tsx`
- `inception/{SessionList,FileIndexer}.tsx`

### 验证结果

- ✅ `tsc --noEmit` 零错误
- ✅ `vite build` 通过（138 modules, ~792ms）
- ✅ 类型安全：全部用 CSS var 而非硬编码 zinc-*/blue-*
- ⏳ **视觉验收待用户启动 dev 实际查看**（Phase 13 测试 36→140 后端逻辑验证已通过）

### 关键决策

- **暗色模式**：当前 token 系统支持，但页面级未全部适配 → 用户要求"先按白色版本做，黑色后面补"
- **MCP 工具授权 UX**：用户单独追问，已设计完整方案并写入 `plan.md` 末尾 "待定" 章节，等后续 wire 接

---

## Phase 13 — 测试补强 + 代码审查（2026-05-12）

### 完成内容

| 模块 | 说明 |
|------|------|
| 代码审查报告 | `docs/REVIEW_2026-05-12.md`（架构 A、测试 C+、文档 A、综合 B+） |
| conftest.py | `FakeCRUD/FakeEventBus/FakeLlmGateway/FakeMCPPool/FakeWSManager` 测试夹具 |
| 新增测试 | 7 个新测试文件，36→**140** pytest（+289%） |
| log_svc 桩填充 | NotImplementedError → 内存环形缓冲区实现 |
| event_bus bug fix | `structlog.error()` 的 `event=` 参数冲突 |

### 新增测试文件
- `test_task_runner.py`（15 tests）— TaskRunner 输入/输出/重试/执行顺序
- `test_state_machine_edge.py`（13 tests）— 状态机边界用例
- `test_workflow_svc.py`（17 tests）— WorkflowService 编排逻辑
- `test_inception_svc.py`（20 tests）— InceptionService 会话/蓝图
- `test_project_svc.py`（14 tests）— ProjectService CRUD/克隆
- `test_mcp_svc.py`（19 tests）— McpService CRUD/连接池/序列化
- `test_event_bus.py`（6 tests）— InMemoryEventBus 订阅/错误隔离

### 验证结果
- ✅ pytest **140/140 passed**（11→36→140，累计 +1173%）
- ✅ 后端 75 API routes 不变
- ✅ 类型检查全过

## Phase 12 — Port 层补全 + 测试覆盖增强（2026-05-11）

### 完成内容

| 模块 | 说明 | 状态 |
|------|------|------|
| LlmPort | `backend/ports/llm_port.py` — LLM 抽象接口 Protocol | ✅ |
| RepoPort | `backend/ports/repo_port.py` — 数据持久化抽象接口 Protocol | ✅ |
| ports/__init__.py | 统一导出所有 Port（EventBus/Interaction/LLM/MCP/Repo） | ✅ |
| 状态机 bug 修复 | `PENDING→PAUSED` 和 `PAUSED→PENDING` 转换缺失，已补全 | ✅ |
| Port 测试 | `test_ports.py` — 6 个测试验证 Port 导入与数据类 | ✅ |
| 工作流逻辑测试 | `test_workflow_logic.py` — 19 个测试覆盖状态机/DAG/输出校验 | ✅ |
| E2E 测试恢复 | `frontend/e2e/smoke.spec.ts` 重建（6 个冒烟测试） | ✅ |

### 新增/修改文件

#### 后端 — Port 层
- `backend/ports/llm_port.py` — **新增**：LlmPort Protocol + LlmMessage/LlmUsage/LlmResponse 数据类
- `backend/ports/repo_port.py` — **新增**：RepoPort Protocol（CRUD + paginate 抽象）
- `backend/ports/__init__.py` — **重写**：统一导出所有 5 个 Port 接口

#### 后端 — Bug 修复
- `backend/domain/harness/states.py` — **修复**：
  - `TASK_TRANSITIONS[PENDING]` 增加 `PAUSED`（暂停时截断后续链）
  - `TASK_TRANSITIONS[PAUSED]` 增加 `PENDING`（恢复时恢复等待态）

#### 后端 — 测试
- `backend/tests/test_ports.py` — **新增**：6 个 Port 接口测试
- `backend/tests/test_workflow_logic.py` — **新增**：19 个领域逻辑测试
  - 5 个项目状态机测试（start/pause/resume/abort/invalid transition）
  - 6 个任务状态转换测试（线性完成/并行 fork-join/失败阻塞/验证失败/重试/进度追踪）
  - 4 个 DAG 验证测试（合法线性/合法并行/环路检测/引用完整性）
  - 4 个输出 schema 校验测试（合法/缺必填/空 schema/类型不匹配）

#### 前端 — E2E
- `frontend/e2e/smoke.spec.ts` — **恢复**：6 个 Playwright 冒烟测试

### 验证结果
- ✅ pytest **36/36 passed**（从 11 增长到 36）
- ✅ 前端 tsc 零错误
- ✅ Port 层完整覆盖 plan §2.2 定义的 5 个接口

### 当前统计
- 后端 **75 API routes**
- 后端 **36 个测试**（11→36，+227% 增长）
- Port 层：5 个 Protocol 接口完整（EventBus/Interaction/LLM/MCP/Repo）
- LLM 支持：OpenAI + Anthropic 双 adapter
- 前端 tsc 零错误

---

## Phase 11 — LLM Gateway + Lifecycle API（2026-05-10）

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

## Phase 9-10 记录

- `frontend/src/stores/useThemeStore.ts` — Zustand 持久化主题 store（light/dark/system 三态循环）
- `frontend/src/components/layout/ErrorBoundary.tsx` — React 错误边界，带重试按钮
- `frontend/src/components/layout/AppShell.tsx` — 集成 ErrorBoundary + 主题初始化
- `backend/mycrew_backend.spec` — PyInstaller 打包规格（单文件 exe）
- `src-tauri/tauri.conf.json` — 增加 `externalBin` sidecar 配置
- `scripts/build.py` — 一键构建脚本（PyInstaller → copy binary → cargo tauri build）

## 剩余可选工作
- 实际 PyInstaller 打包验证（需要完整 Python 环境 + 依赖安装）
- cargo tauri build 出安装包
- E2E 测试实际运行（需 `pnpm e2e:install` 安装 Playwright 浏览器）
