# 2026-05-15 迭代记录

整天围绕 **Plan Maker 工作流可靠性** 展开。从 prompt 优化、按需 LLM 分层、Unity MCP 接通、UI 一致性，逐步深入到发现 PM 当前架构在 Unity 复杂场景下的根本性短板，最后落到 **PM v3 — 5-phase Crew 重写**的完整设计。

## Commit 列表（按提交顺序）

| # | Hash | 主题 | 一句话 |
|---|---|---|---|
| 1 | `78a8010` | feat(plan-maker): per-intent prompts + 3-tier LLM picker | 每个 sub-agent 自带 (LLM 偏好 / temperature / max_tokens)；compliance/intent 走 cheap、create/iterate/modify 走 pro |
| 2 | `b6d76f0` | fix(path-picker): surface dialog errors + drop ellipsis | 「浏览…」→「浏览」；非 Tauri 环境检测 + 错误 alert 而非静默 fallback |
| 3 | `3536526` | feat(create_new): detect + self-heal half-finished 3-step kickoff | 后置 validate + 缺啥补啥的焦点修复 kickoff；max_iter 5→8 |
| 4 | `9012836` | feat(unity-template): register MCP for Unity + Assets/Fonts/ | 4 个 Unity 模板加 Assets/Fonts/；render_template_context 加「项目预置环境」块 |
| 5 | `6c9f178` | feat(unity-mcp): wire 34 Unity MCP tools into agent runtime | 把 src/tools/builtin/unity/ 从根 src 挪到 backend/src；seed + crewai_runner 第三 lookup + 真工具名替换 v2 命名 |
| 6 | `490c9bf` | feat(inception): progressive blueprint reveal + dedupe pending bubble | 新增 `inception.drafting_started` + DraftingSkeleton；agents_assigned 带 assignments map；用户气泡去重 |
| 7 | `77b1d5c` | feat(plan-maker): per-stage IO trace + unified thinking subframe | 新增 `plan_maker.sub_agent_io` WS 事件 + LogDrawer 渲染；统一 thinking 子框（始终打开） |
| 8 | `2764b23` | ui(agent-chat): align task-card agent chat with Plan Maker drawer | 任务卡片 Agent 对话用主题色变量；微信绿气泡；340→400px |
| 9 | `c68e704` | feat(task): persist task input + guidance chat + stalled-start warning | `io_in_ref` 真落盘；`/workflow/tasks/{id}/guidance` 任务诊断助手；start 受阻提示 |
| 10 | `439ee53` | feat(task): specific failure reason on the amber warning badge | migration 0012 加 `last_error` / `last_error_kind`；workflow_svc 启发式分类；TaskNode tooltip 显示中文具体原因 |
| 11 | `1c279f7` | feat(agent-editor): add LLM model selector beside provider | 服务商→模型版本 两级选择；llm_id 拼回 `<prov>:<model>` |

## DB 维护（未 commit）
- 删 4 行死链 `unity_*_file`（路径指向 `src/tools/unity_file_tool.py` 不存在），tools 表 81 → 77 行

## 主要议题脉络

### 早段：PM 子 agent prompt 按意图分化（`78a8010`）
痛点：5 个 sub-agent 共用 session 的同一个 LLM + 默认温度，没按意图特点分配资源。
方案：每个 sub-agent 自带 DEFAULT_PARAMS；新建 `_llm_picker.pick_llm(session, preference)` 三档（cheap/default/pro）。

### 中段：Unity MCP 接通（`9012836` + `6c9f178`）
发现：`src/tools/builtin/unity/` 已有 34 个工具壳 + `_UnityMcpPool` 连接池，但**整个 backend 没人 import**。因为位置错（在根 src/ 而非 backend/src/）。
方案：迁移 + 加入 seed + 加入 crewai_runner 第三 lookup 分支 + 替换 assign_agents role-keyword 白名单的工具名。

### 后段：任务可观测性深挖（`c68e704` + `439ee53`）
痛点：任务卡片黄标只显示"需要用户介入"，没具体原因。
方案：DB 加列 + workflow_svc 启发式分类 + TaskNode tooltip 渲染中文具体原因（Token 配额不足 / MCP 依赖未连接 / 网络问题 / ...）。同时实现任务卡 Agent 对话改成真 LLM（[task_guidance.py](../../../backend/agents/task_guidance.py)），并且严格只读 + 拒绝替用户操作。

### 收官：发现 PM 架构根本短板
现实案例：「赛博朋克跳跃求生」多个 task validation_failed，根因是 task detail 没注入「调 emit_output」指令。

这不是「prompt 调一调就好」的事 — 现有 PM 是「一次 kickoff + 3 工具串调」整体 LLM 临时忘规则的概率不可忽视。**需要把 PM 改成 5-phase Crew + 强校验契约 + 高可控**。

→ 10 轮 grill-me 出最终方案，见 [PM v3 grill 问答](./pm-v3-grill-transcript.md) + [PM v3 最终方案](./pm-v3-plan.md)。

## 教训 / 复盘

1. **prompt 软约束 ≠ 校验**。规则写在 LLM prompt 里 = 软约束，LLM 概率性忘记。要保证 = 需要后置代码校验 + 失败让 LLM 自纠。`emit_output` 是个好范式但只覆盖了 task execution 层，PM 层完全没有。
2. **跨目录 import 静默失败**。Unity tools 放错位置后无人引用、无错误日志，全靠某天用户问"为什么 Unity MCP 不工作"才暴露。**应有 startup-time 检查**：tools 表里所有 builtin 名字必须能在 import path 里解析到，否则警告。
3. **WS 事件传输是 transient log**。`task.failed` 事件携带 error 信息但不入 DB → 浏览器刷新就丢。今天加了 `last_error` / `last_error_kind` 列才补上。**任何对调试有用的信息，DB 持久化 + WS 广播两条腿走路**。
4. **死链 DB 行**。seed 是幂等的，删掉 seed 行不会清 DB 老数据。**未来对 seed 改 schema 的迁移，需要额外清理脚本**。
5. **"看起来一致"的 UI 不一定真一致**。AgentChatDrawer 写了 `dark:bg-zinc-900` 但用户报"黑白模式颜色反了" — 因为整体颜色系统是 CSS 变量驱动的，硬编码 Tailwind 类绕过了主题。**统一用 design token，禁止任何颜色硬编码**。
6. **"复杂的 UI 交互方案" > "AI 容错"**。用户明确说：当前用户对 AI 产品的容错耐心较足，但对复杂 UI 不耐受。所以 PM v3 设计里所有"加按钮让用户选"的方案都被拒，宁可让 LLM 自己决定 + 显式失败再补救。这是个值得记住的产品决策默认值。

## 待办（明天起）

- [ ] 执行 PM v3 实施分阶段 A-I（[pm-v3-plan.md](./pm-v3-plan.md)）
- [ ] iterate_existing 按同模式重写（PM v3 稳定 2-3 周后）
- [ ] 完整单测覆盖 PM v3（同上）

## 文件索引
- [pm-v3-grill-transcript.md](./pm-v3-grill-transcript.md) — 10 轮问答原始记录 + 每轮最终决定
- [pm-v3-plan.md](./pm-v3-plan.md) — 最终落地方案（同 plan 文件）
