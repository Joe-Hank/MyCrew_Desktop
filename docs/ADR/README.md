# docs/ADR/

架构决策记录（Architecture Decision Records）。

## 命名规范

`NNNN-kebab-case-title.md`，例如：
```
0001-shell-tauri-2.md
0002-pure-structured-project-instructions.md
0003-single-project-running.md
```

## 必备 ADR（Phase 0 落地）

参 plan §16，至少落地以下 8 条：

| 编号 | 决策 |
|---|---|
| 001 | 桌面壳层选 Tauri 2.x 而非 Electron |
| 002 | 项目"指令"纯结构化入 DB，不再生成 YAML |
| 003 | 同时只能运行一个项目 |
| 004 | LLM 记录 = 1 provider+key 配多 model（嵌套表） |
| 005 | 用户 Tool 必须是 CrewAI BaseTool 子类 |
| 006 | 自动生成 Agent/Crew 入全局库带 `auto-generated` 徽章 |
| 007 | 项目根目录仅作为 Agent 默认产出路径，不限制读写 |
| 008 | InteractionPort 通过 WS `prompt.request/response` 替代 input() |

## ADR 模板

```markdown
# NNNN. {决策标题}

## Status

Accepted | Superseded by ADR-XXXX | Deprecated

## Context

为什么需要这个决策？背景、约束、考虑过的方案。

## Decision

明确决定做什么。

## Consequences

正面、负面、中性影响。哪些后续工作受此决策约束。

## References

相关 plan / PRD / Issue / Discussion 链接。
```

## 何时新写一条 ADR

满足三条全部时（参 grill-with-docs 准则）：
1. **难以反转** —— 改变心意的代价大
2. **不带上下文会让人困惑** —— 未来读者会问"为什么这样做？"
3. **真权衡的结果** —— 有真实备选，因为特定原因选了某个

## 不写 ADR 的情况

- 一时的实现选择
- 行业标准做法
- 无真实备选的决策
