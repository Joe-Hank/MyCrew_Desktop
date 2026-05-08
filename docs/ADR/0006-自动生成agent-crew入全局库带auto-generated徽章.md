# 0006. 自动生成 Agent/Crew 入全局库带 auto-generated 徽章

## Status

Accepted

## Context

MyCrew v3 的 Inception（项目规划）功能允许 LLM 根据用户的项目描述自动规划任务、分配 Agent，并在必要时创建新的 Agent 和 Crew。这引发了一个重要的设计问题：Inception LLM 自动创建的 Agent/Crew 应该如何管理？

### 问题场景

假设用户创建了一个"市场调研"项目，Inception LLM 判断需要以下 Agent：
- "市场分析师"——用户已经在全局库中创建过，直接引用
- "数据采集专员"——全局库中不存在，Inception 需要创建

对于第二种情况，我们面临几个选择：

### 方案 A：仅在项目内创建，不入全局库
- 问题：如果另一个项目也需要"数据采集专员"，Inception 会重复创建，导致碎片化
- 问题：用户无法在 Team 页面统一管理所有 Agent

### 方案 B：直接入全局库，与用户创建的 Agent 无区别
- 问题：用户无法区分自己精心配置的 Agent 和 AI 随手生成的 Agent
- 问题：全局库可能被大量低质量的自动生成 Agent 污染

### 方案 C：入全局库，但标记来源（本决策）
- 自动生成的 Agent/Crew 存入全局表，但带有 `is_auto_generated` 标记
- 前端通过徽章（Badge）视觉区分
- 用户可以"提升"（promote）为正式 Agent

## Decision

Inception LLM 自动创建的 Agent 和 Crew 进入全局库（`agents` / `crews` 表），并标记 `is_auto_generated = true`。

### 数据模型

在 `agents` 和 `crews` 表中添加以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| is_auto_generated | BOOLEAN | 是否为 AI 自动生成，默认 false |
| generated_by_project | TEXT (FK) | 首次生成此 Agent 的项目 ID（可选） |
| promoted_at | DATETIME | 用户提升为正式 Agent 的时间（NULL 表示未提升） |

### 前端展示

- **Team 页面**：自动生成的 Agent/Crew 显示 `🤖 自动生成` 徽章
- **筛选功能**：支持按来源筛选（全部 / 用户创建 / 自动生成）
- **提升操作**：用户点击"确认保留"按钮后，清除 `is_auto_generated` 标记，设置 `promoted_at` 时间戳

### Inception 行为

1. Inception 规划任务时，首先在全局库中搜索匹配的 Agent（按 role、goal 相似度）
2. 如找到匹配的 Agent（无论是否为自动生成），直接引用
3. 如无匹配，创建新 Agent 并标记为 `is_auto_generated = true`
4. 同一个自动生成的 Agent 可被多个项目复用

## Consequences

**正面影响：**

- 来源可追溯：用户始终知道哪些 Agent 是自己创建的，哪些是 AI 生成的
- 全局复用：自动生成的 Agent 可被后续项目复用，避免重复创建
- 渐进式信任：用户可以先使用 AI 生成的 Agent，确认质量后再"提升"为正式成员
- 审计友好：通过 `generated_by_project` 可追溯 Agent 的生成上下文

**负面影响：**

- Team 页面列表可能因大量自动生成的 Agent 而变得冗长
- 用户可能忽略"提升"操作，导致大量 Agent 长期处于 `auto-generated` 状态
- 需要额外的 UI 空间来展示徽章和筛选控件

**中性影响：**

- 未来可以添加自动清理功能：长期未被引用的自动生成 Agent 可提示用户删除
- 提升机制为后续的"Agent 市场"或"Agent 模板"功能奠定基础

## References

- plan.md §4（数据模型 - agents 表、crews 表字段定义）
- plan.md §5（后端服务 - inception_svc 自动创建逻辑）
- plan.md §8（前端 - Team 页面 Agent 列表与筛选）
