# docs/ — 文档索引

按用途分四档：**程序说明**（稳态）→ **迭代日志**（时间线）→ **未来规划**（待办）→ **历史归档**。

> **找具体内容？** 用主题反查表 → [`INDEX.md`](./INDEX.md)
>
> 本文件是**目录导航**（按子目录分），[`INDEX.md`](./INDEX.md) 是**主题查找**（按关键词 / 动词 / 故障症状反查具体段落 + 代码文件）。两份互补，找东西先看 INDEX。

## 目录速查

| 子目录 | 用途 | 你什么时候来这里 |
|---|---|---|
| [`spec/`](./spec/) | 程序说明文档（稳态，跟代码一起演进） | 想知道某个模块怎么用 / 怎么搭 |
| [`iterations/`](./iterations/) | 迭代日志（按日期归档） | 想看「某一天我们改了什么、为什么改」 |
| [`ADR/`](./ADR/) | 架构决策记录 | 想知道某个设计选项背后的取舍 |
| [`roadmap/`](./roadmap/) | 未来规划（backlog + 设计草案） | 想知道「下一步该做什么、触发条件是什么」 |
| [`dev-notes/`](./dev-notes/) | 开发笔记、调试踩坑 | 跑代码遇到怪现象时先看这里 |
| [`figma/`](./figma/) | 设计稿引用 | UI / 视觉相关 |
| [`archive/`](./archive/) | 一次性 audit / review 报告，已被新文档替代 | 翻历史 |

---

## `spec/` — 程序说明文档

跟代码一起呼吸，被改的频率跟相应模块同步。

| 文件 | 内容 |
|---|---|
| [`ARCHITECTURE.md`](./spec/ARCHITECTURE.md) | 架构定稿（Domain/Services/Infra/API 分层 + 数据流） |
| [`API.md`](./spec/API.md) | REST + WebSocket 契约 |
| [`STORAGE-MAP.md`](./spec/STORAGE-MAP.md) | DB schema + 文件落盘约定 |
| [`DESIGN-SYSTEM.md`](./spec/DESIGN-SYSTEM.md) | 前端设计系统（**DEFAULT 默认风格**） |
| [`BUILD.md`](./spec/BUILD.md) | 开发启动 + 打包流程 |
| [`USER_GUIDE.md`](./spec/USER_GUIDE.md) | 首次使用 / 配置 / 故障排查 |

---

## `iterations/` — 迭代日志（按日期）

| 日期 | 主题 |
|---|---|
| [`2026-05-15/`](./iterations/2026-05-15/) | PM v3 5-phase 设计 + 落地 |
| [`2026-05-16/`](./iterations/2026-05-16/) | PM v4 Crew-Native + 架构 audit |

写迭代日志的约定见 [`iterations/2026-05-15/README.md`](./iterations/2026-05-15/README.md)：每个迭代单独一个目录，目录里放当天的 plan / grill / 落地报告。

---

## `roadmap/` — 未来规划

按"触发条件"组织，**不到触发不动**。

| 文件 | 内容 |
|---|---|
| [`next-audit-prep.md`](./roadmap/next-audit-prep.md) | **下次技术审核的开局地图** — 60s 快照 / 应补维度 / 风险监视 / 下个 Top 5 候选 / 迭代草案 / 索引 |
| [`phase2-backlog.md`](./roadmap/phase2-backlog.md) | 优化项的 backlog（已分本轮执行的 / 仍待办的 6 项） |
| [`phase3-deferred-to-packaging.md`](./roadmap/phase3-deferred-to-packaging.md) | 跟打包/SaaS 化绑的延后事项（LLM key 加密、CSP、tenant_id 等） |
| [`mcp-export-server-design.md`](./roadmap/mcp-export-server-design.md) | `mycrew-export-mcp` 设计草案（暴露 MyCrew 能力给外部 Agent） |
| [`openclaw-integration-plan.md`](./roadmap/openclaw-integration-plan.md) | OpenClaw 集成预案（A/B/C 三方向决策树） |

---

## `ADR/` — 架构决策记录

8 条已锁定的决策（Tauri 2.x、PM v3 入 DB 不 YAML、单项目限制等）。新决策按 `0009-<short-title>.md` 添加。

---

## `archive/` — 历史归档

被新版本替代的一次性报告。**只读**，不再更新。

| 文件 | 被替代为 |
|---|---|
| `REVIEW_2026-05-12.md` | `iterations/2026-05-16/architecture-audit.md`（更全面的本轮 audit） |
| `_tmp_PLAN_MAKER_PROMPTS_AUDIT.md` | `iterations/2026-05-15/` 里的 PM v3 plan 已收口 |

---

## 写作约定

- Markdown CommonMark；中文为主，专有名词保留英文（CrewAI、FastAPI 等）。
- 代码块带语言标注（`python` / `ts` / `bash` / `sql`）。
- 文件路径用反引号包裹：`backend/services/workflow_svc.py:123`。
- 跨文档引用用相对链接：`[..](../iterations/2026-05-16/architecture-audit.md)`。
- 每个文档**顶部加一段「干什么用 / 什么时候读 / 当前状态」**，让读者 5 秒判断是否要继续看。
- 重大变更在文件头加「最后更新：YYYY-MM-DD + 一句变更说明」。

---

## 给未来的我：哪里写什么

- **新加了某个 service 怎么用** → `spec/ARCHITECTURE.md` 加一段
- **改了 schema / 加了 migration** → `spec/STORAGE-MAP.md` 加一段 + 在 `iterations/<日期>/` 写当日日志
- **决定了一个会影响后续 N 个 sprint 的设计** → `ADR/<NN>-<title>.md`
- **当前没做但要做的事** → `roadmap/<feature>-backlog.md`，**必须**写触发条件
- **跑代码遇到的怪现象 + 解法** → `dev-notes/`，标题带日期
