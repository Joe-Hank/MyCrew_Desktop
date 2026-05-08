# frontend/src/components/home/

主页相关组件。

## 组件清单

| 组件 | 职责 |
|---|---|
| `ProjectGrid.tsx` | 项目卡片分页网格（4×N，最多 100 张/25 页），底部分页器 |
| `ProjectCard.tsx` | 单卡片：标题 / 复制 / 删除（输入项目名二次确认）/ 创建日期 / 进度 / 开始或继续按钮 / 路径按钮 / 迭代占位 / 任务子列表（标题+Agent+换 Agent 下拉） |
| `McpStatusBar.tsx` | 单行横向滚动；30s 心跳；右侧"连接"按钮触发强制全量重连 |
| `TokenBar.tsx` | 单行横向滚动；30s 自动 + 手动刷新；显示规则：百分比/M 数/绿红圆点三态 |

## 数据来源

- 项目列表 → `useProjectsQuery({ page, size: 4 })`
- MCP 状态 → `useMcpStatusQuery()` + WS `mcp.connected/disconnected` patch cache
- Token 用量 → `useLlmQuotaQuery()` + WS `llm.quota_changed` patch cache

## 关键交互

- "新建项目"按钮 → `useUIStore` 设置 `inceptionDrawerOpen=true` → 打开抽屉（在 inception/ 下）
- 同时只能运行一个项目：点开始/继续若已有 running 项目 → 弹"请先暂停 X，是否暂停并切换？"模态
- 项目运行中关闭路径按钮：仅"打开文件管理器"（调 Tauri invoke）
