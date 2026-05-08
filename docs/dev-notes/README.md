# docs/dev-notes/

各阶段开发记录、调试笔记、踩坑。

## 命名规范

按阶段或日期组织：

```
dev-notes/
├─ phase-0-scaffolding.md
├─ phase-1-end-to-end-skeleton.md
├─ phase-2-config-credentials.md
├─ phase-3-mcp-pool.md
├─ phase-4-harness.md
├─ phase-5a-inception-readonly.md
├─ phase-5b-blueprint-editable.md
├─ phase-5c-history-drafts.md
├─ phase-6-task-page.md
├─ phase-7-team.md
├─ phase-8-settings.md
├─ phase-9-package.md
└─ debug/
   └─ {YYYY-MM-DD}-{short-slug}.md
```

## 内容建议

每份阶段笔记含：

- **目标**（plan 中该 phase 的交付清单）
- **实际实现**（与计划的偏差与原因）
- **遇到的问题** + 解决方案
- **新发现的需求**（feed 回 plan）
- **手动冒烟清单**（plan §17 验收标准的本阶段切片）

## 与 ADR 的区别

- ADR：**决策**（为什么选 A 不选 B）；持久；很少改
- dev-notes：**记叙**（发生了什么）；阶段性；可堆叠

## 与 plan.md 的关系

- plan.md 是设计阶段产物；冻结后不改
- 实施中发现 plan 需调整 → 在 dev-notes 中记下偏差 + 原因 → 必要时新增 ADR 记录决策变更
- 不直接改 plan.md（保持历史完整性）
