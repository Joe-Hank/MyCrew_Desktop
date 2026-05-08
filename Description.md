# MyCrew v3

## 项目定位

CrewAI + MCP 的本地服务窗口（PC 桌面应用），用于多 Agent 工作流的可视化管理。

## 与 v2 的关系

v2（`F:\ClaudeData\MyCrew_v2`）已实现完整桌面应用但因整体用户体验不佳、核心功能不稳定被弃用。v3 在空目录从零重构，参考 v2 的 IMPLEMENTATION_GUIDE.md 但不复用 v2 代码。

## 核心特性

- 对话驱动的项目立项（LLM 帮助拆解任务并自动选 sequential/Crew/Flow 执行结构）
- 任务输出契约化（每个 Task 有 output_schema，跨 Task 边界 Pydantic 校验）
- MCP 工具手写包装（解决 v2 dynamic MCP integration 参数报错问题）
- 项目级 final QA Task（DAG 末端固定节点，输出 verdict 决定项目最终状态）

## 关键设计决策

详见 `docs/ADR/`，要点：
- 桌面壳：Tauri 2.x（v2 用过 Tauri 失败的根因是耦合架构而非 Tauri 本身）
- 项目"指令"纯结构化入 DB，不再生成 YAML
- 同时只能运行一个项目（schema 已为未来并发预留 `is_running` 字段）
- 用户 Tool 必须是 CrewAI BaseTool 子类
- InteractionPort 通过 WS `prompt.request/response` 替代 input()

## 文档主入口

[plan.md](./plan.md) 是权威设计文档，包含完整架构、模块清单、实施路线、PRD 对齐细节。

## PRD 来源

Notion 页面 `MyCrew项目系统设计`：
- 总目录: https://www.notion.so/3578e10c17cc801b9df6e2e5888b6cff
- 主页 PRD / 任务页 PRD / 团队页 PRD / 设置 PRD（四子页）

## Figma 原型

https://www.figma.com/design/1sr0yP4OSIpokBszeNkwYV/MyCrew?node-id=0-1
- 主页 node `5:25`、任务 `33:4683`、团队 `33:4685`、设置 `33:4684`

## 不在 MVP 范围

明确推迟，避免功能蔓延：
- 自动更新
- 多项目并发运行
- 系统权限的路径白名单与审批弹窗
- RAG 文件索引
- 国际化（中文优先，i18next 仅占位）
- 任意第三方 LLM provider 插件
