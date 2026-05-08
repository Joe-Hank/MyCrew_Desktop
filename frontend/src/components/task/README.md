# frontend/src/components/task/

任务页核心交互组件。

## 组件清单

| 组件 | 职责 |
|---|---|
| `ProjectHeader.tsx` | 标题 / 进度 / 开始-暂停按钮 / 路径按钮 / 迭代占位 |
| `Blueprint.tsx` | DAG 蓝图主视图：固定宽自适高节点、串联顶部对齐、并联上下排列、曲线连接；缩放/平移；项目暂停态下右上角"+ 新增任务"按钮 |
| `TaskNode.tsx` | 单任务节点：标题 / Agent 信息 + Agent 变更下拉（项目运行中禁用）/ 进度 / 详情 / 更多操作菜单 |
| `AgentChatDrawer.tsx` | Agent 对话面板（仅任务失败/不可执行时可用）；下方面板嵌入：输入框 + 反馈框；延续失败上下文 |
| `IoViewerDrawer.tsx` | 左拉半页 IO 查看器；两个 Tab：结构化数据（按 output_schema 渲染）/ 原始过程（聊天记录 + Tool trace） |

## 任务节点操作菜单

- 编辑详情（项目运行中禁用）
- 任务级开始-暂停（已开始/已完成的不可暂停；暂停=任务链断点）
- 重新执行（仅"已完成且非运行中"可用，二次确认含"级联重跑下游"勾选）
- 打开 Agent 对话（仅任务失败/不可执行时可用）
- 查看输入信息 / 查看输出信息（左拉半页双 Tab）

## 暂停语义（在状态条）

- 项目暂停按钮旁显示"正在等待 Task X 完成…{已耗时}"
- 提供"强制中断"按钮（二次确认）→ 抛断 LLM 调用 → Task 标 `aborted`，下次继续时该 Task 重跑

## 数据来源

- `useTasksQuery({ projectId })` + WS `task.*` 事件 patch cache
- IO 查看：`GET /tasks/:id/io?direction=in|out` 按需拉取
