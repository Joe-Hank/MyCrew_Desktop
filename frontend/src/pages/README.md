# frontend/src/pages/

4 个顶层页面。每个页面对应路由树的一个 leaf。

## 页面清单

| 页面 | 文件 | Figma node | 关键交互 |
|---|---|---|---|
| 主页 | `HomePage.tsx` | `5:25` | 项目卡片网格（4×N 分页）、新建项目入口、MCP 状态条、Token 监控条 |
| 任务 | `TaskPage.tsx` | `33:4683` | ProjectHeader、DAG 蓝图、TaskNode 操作菜单、Agent 对话抽屉、IO 查看抽屉 |
| 团队 | `TeamPage.tsx` | `33:4685` | 三 Tab：Agents / Crews / Tools；左侧黄金分割编辑抽屉 |
| 设置 | `SettingsPage.tsx` | `33:4684` | 三 Tab：LLM / MCP / 系统权限；左侧编辑抽屉 |

## 页面级约束

- 页面文件**只组合组件**，不写业务逻辑
- 业务逻辑下沉到 `components/<page>/` 下的具体组件
- 跨组件状态用 store 或 query；不向下钻 props drilling 超过 2 层

## 路由约定（Phase 1 落地）

```
/          → HomePage
/tasks     → TaskPage（参数 ?project=...）
/team      → TeamPage
/settings  → SettingsPage
```

## 不在范围

Figma 中的 `backup` 页不实现路由（已在 plan §Context 标注）。
