# frontend/src/components/inception/

项目立项半页抽屉（核心新增交互）。

## 组件清单

| 组件 | 职责 |
|---|---|
| `InceptionDrawer.tsx` | 顶层抽屉容器；黄金分割宽度（约 37% 屏宽，可拖拽并记忆）；草稿静默自动保存 |
| `ChatPane.tsx` | 中栏消息流（流式渲染）+ 输入框 + 文件索引按钮 |
| `TaskBlueprintEditor.tsx` | 右栏：AI 拆解的任务模块编辑器（标题/详情/Agent/前置依赖/output_schema） |
| `FileIndexer.tsx` | 文件/目录索引选择器（多次添加，可移除） |

## 关键行为

- **顶部**：LLM 二级选择（Provider → Model）+ 思考模式开关（仅当 model.supports_thinking=true 启用，否则灰显）；预选取 `default_inception_model`
- **左栏**：历史会话列表（每项对应一个 project，带状态徽标；草稿带 `[草稿]` 标记）+ "新建会话"
- **右栏**：任务模块编辑；右上角"让 AI 重新评估架构"按钮 → 触发 LLM 复核 sequential/Crew/Flow
- **底部**：确认 → 生成项目卡（`POST /inceptions/:id/finalize`）

## 数据流

- `POST /inceptions` 开会话 → `POST /inceptions/:id/messages` SSE 流回 → `inception.delta` WS 事件追加 → `inception.tasks_drafted` WS 事件刷新右栏
- 文件索引：`POST /inceptions/:id/index-path`，自动选 A 或 C 模式（≤200KB 全文 / 超量目录树+按需 file_read）

## 草稿持久化

- 关闭抽屉/应用 → 静默自动保存到 `inception_sessions`（status=draft）
- 抽屉顶部"丢弃草稿"按钮供主动清理
- 重启后历史会话列表显示 `[草稿]` 标记可点回继续
