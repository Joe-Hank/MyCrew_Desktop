# frontend/src/components/

按页面/职责分组的 React 组件。

## 子目录

| 目录 | 内容 |
|---|---|
| `layout/` | 应用骨架：AppShell、Sidebar、LogDrawer（带多终端 Tab 切换） |
| `home/` | 主页：ProjectGrid、ProjectCard、McpStatusBar、TokenBar |
| `inception/` | 立项半页抽屉：InceptionDrawer、ChatPane、TaskBlueprintEditor、FileIndexer |
| `task/` | 任务页：ProjectHeader、Blueprint（DAG 渲染）、TaskNode、AgentChatDrawer、IoViewerDrawer |
| `team/` | 团队页：AgentList、CrewList、ToolList、EditorDrawer（多形态：AgentForm / CrewForm / ToolForm） |
| `settings/` | 设置页：LlmList、McpList、PermissionMatrix、EditorDrawer |
| `ui/` | 通用 UI Kit：Modal、Toast、StatusDot、Empty、Skeleton 等 |

## 约定

- 一个文件一个组件；同名 `.test.tsx` 与组件同目录
- 组件内不直接调 fetch / WS / Tauri；通过 `queries/` `stores/` `hooks/` 取数
- 复杂组件用 colocation：`Blueprint/` 子目录含 `index.tsx` + 内部模块
