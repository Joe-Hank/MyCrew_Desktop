# src/agents/

**（可选）用户预置 Agent 模板 YAML**。

## 现状

PRD 与 plan 中提到这是"可选"功能，主要 Agent 在团队页通过 UI 表单创建并入库到 `agents` 表。本目录用于**离线/批量预置**场景：

- 项目首次部署时希望预置一组通用 Agent 模板（如"代码审阅员""技术文档写手"）
- 用户在多机间同步 Agent 配置（git 管理 YAML 比 SQL dump 友好）

## 待确认细节（Phase 7+ 决定）

> 本目录在 MVP 阶段**可能不实现**——Phase 7 开工前评估。当前若不需要批量预置，可保持空目录。

**未定义事项**：

1. **YAML schema** —— 待 Phase 7 落地时定义。候选格式：
   ```yaml
   # src/agents/code_reviewer.yaml
   role: 代码审阅员
   goal: 审阅代码并提出改进建议
   backstory: 资深工程师...
   reasoning: true
   max_retry: 3
   memory_enabled: true
   thinking_mode: false
   tool_ids: [my_search, file_read]
   llm: { provider: anthropic, model: claude-opus-4-7 }
   ```
2. **加载时机** —— 启动期加载（与 `tool_svc.scan` 同步）vs 用户在团队页点"导入 YAML"按钮
3. **冲突解决** —— 与 DB 已有同名 Agent 冲突时：覆盖 / 跳过 / 用户决定
4. **导出反向** —— 团队页 Agent 是否支持"导出为 YAML"（便于备份/迁移）

**MVP 决策**：**先不实现**，保留目录与本 README 占位。如 Phase 7 用户提出明确需求再做。

## 与团队页 Agent 的关系

- 团队页 Agent CRUD 是主路径（DB 是真相源）
- 本目录 YAML 是辅助导入路径（导入后入 DB，运行时不再读 YAML）

## 当前状态

- 目录占位
- 不在 MVP 范围
- 留 .gitkeep 防止空目录被 git 忽略
