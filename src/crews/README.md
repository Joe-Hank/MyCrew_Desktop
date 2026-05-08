# src/crews/

**（可选）用户预置 Crew 编排 YAML**。

## 现状

与 `src/agents/` 同理：MVP 阶段主路径是团队页 UI 表单创建。本目录用于离线预置/批量同步场景。

## 待确认细节（Phase 7+ 决定）

> MVP 阶段**可能不实现**。

**未定义事项**：

1. **YAML schema** —— 候选格式：
   ```yaml
   # src/crews/dev_team.yaml
   name: 研发小队
   process: sequential   # sequential | hierarchical（hierarchical 实验性）
   agents:
     - code_reviewer
     - tech_writer
     - qa_engineer
   ```
2. **agent 引用** —— 用 role 名 / 用 YAML 文件名 / 用 DB id？
3. **加载时机** —— 同 src/agents/ 议题
4. **冲突解决** —— 同上

**MVP 决策**：**先不实现**，保留目录与本 README 占位。如 Phase 7 用户提出明确需求再做。

## 与团队页 Crew 的关系

- 团队页 Crew CRUD 是主路径
- 本目录 YAML 是辅助导入路径

## 当前状态

- 目录占位
- 不在 MVP 范围
- 留 .gitkeep 防止空目录被 git 忽略
