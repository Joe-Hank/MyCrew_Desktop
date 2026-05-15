# PM v3 — 10 轮 Grill 问答记录

`/grill-me` 模式下逐问追到收口。每轮记录：**问题** / **我推荐** / **用户最终拍板**。

---

## Q1 — 5 个 agent 之间传什么"数据"？

**问题维度**：自由文本 + JSON 嵌入（CrewAI 原生默认）vs. 强类型 schema + 代码层校验（Pydantic enforced）。

**我推荐**：B（强类型）+ 渐进式 PlannerTask 模型 — 每 phase 填一组字段，下一个 phase 收到 schema 校验过的 dict。

**用户拍板**：**B + 给配置专有 Tool 协助达到 B 的效果。**

落地：每 phase 配独立提交工具，args_schema 严格 Pydantic，校验失败 LLM 自纠。

---

## Q2 — 5 个工具的"职责边界"怎么切？

**选项**：
- A. 统一多态工具 `submit_phase_output(phase, payload: dict)`
- B. 5 个独立工具，各绑 Pydantic args_schema：`submit_concept` / `submit_atomic_tasks` / `submit_reviewed_tasks` / `submit_pathed_tasks` / `submit_assignments`
- C. 沿用 emit_output

**我推荐**：B —— LLM 看见精确签名是一次过的关键，`emit_output(payload: dict)` 那种模糊签名靠 prompt 描述、pro 模型也经常给错。Pydantic 把字段名/类型编进 function-calling schema 后错的概率断崖式下降。

**用户拍板**：**B**

---

## Q3 — phase 失败时的"重试 / 回退 / 中止"策略？

**3 层防御方案**：
1. Agent 内 self-correct（CrewAI 自带，每 phase max_iter=5）
2. 焦点修复 kickoff（max_iter=3，复用相同 phase 的 pro LLM + 上一次失败原因作为 prompt）
3. 整轮中止：失败半成品不入 DB，debug 窗口红色高亮 + 单按钮给用户

**两个具体询问**：
- 焦点修复用什么 LLM？（推荐：同 phase 的 pro，一致性 > 成本）
- 第 3 层按钮：「整轮重来」+「转手动模式」两个 vs 一个？

**用户拍板**：**A**（一个按钮「整轮重来」即可，drop 半成品，drafting 状态清零）；焦点修复用同 phase 的 pro LLM。

**第 8 轮补充**：把"整轮重来"细化为**「从断点重来」** — 只从失败的那个 phase 开始（上游产物从 cache 取），不再整轮跑一遍浪费 token。

---

## Q4 — 项管 phase 前置的"mkdir 任务"具体怎么模型？

5 个子决策：时机 / 路径来源 / 模板冲突 / 失败处理 / 工具复用。

**我推荐**：B（持久化期 Python 代码 mkdir，不挂 task），路径从 output_paths 自动推导。

**用户拍板**：**1A**（当成真 task，因为 PM 跑时用户还没绑根路径）/ 2A2（Python 推路径）/ 3 用户选择的根目录必然与模板库一致无冲突 / 4 mkdir 失败就卡住 / **5 重新考虑**（既然是真 task，工具用现有 builtin mkdir）。

**关键洞察**：我把时机想错了 — PM 跑的时候 `root_path` 还没绑（创建模式），mkdir 只能是 execution-time 任务。

**总规约（用户备注）**：**"高度可控的、模块化、透明化、可控化"**。

---

## Q5 — mkdir 任务的 agent + 工具 + 调度依赖（重做）

5 个子决策：
- 5.1 用谁来跑这个 task？→ A 新增 seeded 单例「项目初始化助手」+ C Phase 4 pre-assign（Phase 5 不管 setup）
- 5.2 工具用现有 mkdir 还是 Python 直跑？→ 既然是真任务，用 builtin mkdir 工具
- 5.3 下游任务怎么表达"等 setup 完成"？→ A 项管 phase 给所有 regular/final_qa 加 deps=[0]（透明）
- 5.4 setup 任务的 output_schema？→ A `{file_paths: list[str]}` + emit_output 兜底校验
- 5.5 seeded agent 的 prompt → role=「项目初始化助手」、tool_ids=[mkdir, list_directory_local, emit_output]、LLM=cheap

**用户拍板**：**全部按推荐**。

---

## Q6 — 持久化层 — 何时落盘 / 失败回滚 / 幂等

**用户突然引入新约束**：

> 创建后都是在缓存中的，直到用户点击保存，才持久化项目文件。这个是现有系统的问题，一直没来得及改它。另外这个对话状态、缓存都是持久在缓存中的，用户只有关闭程序、开启新对话才会删除这个项目缓存信息。比如我在等待项目任务生成途中去看设置了，不能断掉，关掉对话窗口也不能断掉。

→ 我之前谈的 "5 phase 跑完就持久化" 完全错位，重做 Q6。

**重做的 4 个子决策**：
- 6.1 草稿缓存住哪？→ **A** 后端 in-memory dict `inception_svc._session_drafts`
- 6.2 PM crew 怎么"挂"在后端？→ **保留现有模式**（HTTP 请求 blocked，只是 drawer 关闭不算 cancel）
- 6.3 重新打开 drawer 时如何"恢复现场"？→ **可以**，加 `GET /inception/sessions/{sid}/pm_state` endpoint
- 6.4 「新建对话」/「保存」/「废弃」三个动作的语义 → **不加废弃按钮**

**关键洞察**：drawer 关闭时 DOM 必须保留（render `<div style={{display:'none'}}>` 而非 `return null`），这样 useChatQueue / WS 订阅保持挂载。

---

## Q7 — 取消语义 — Stop 按钮 / 新会话 / 加成中再发

4 个子决策：
- 7.1 Stop 按钮怎么算？→ 用户拍板 **A 真取消 task.cancel + 清缓存**（避免后续 token 浪费）
- 7.2 PM 跑动时用户再发一条新消息？→ **维持现有 chat queue 行为**（排队，PM 完后作为新一轮 — 自然路由到 modify_blueprint）
- 7.3 用户「新建对话」时正在跑的 PM？→ **A 直接 cancel + 清**
- 7.4 关程序？→ **自然消亡**，不做什么

---

## Q8 — 调试日志窗口 — 事件 schema + 生命周期

6 个子决策：
- 8.1 WS 事件类型粒度 → A 单一 `pm.log` + phase 字段
- 8.2 单条事件字段 → 提议 8 个字段，payload_preview 截短到 1KB
- 8.3 后端 in-memory 结构 → `_session_drafts[sid]` 内含 status/current_phase/phase_outputs/debug_log/draft_blueprint/cancel_requested/error
- 8.4 pm_state endpoint 返回 → 上面 dict 去掉 cancel_requested
- 8.5 清理时机 → 保存时 dump trace JSON 到 .mycrew/_planner_trace.json
- 8.6 前端渲染风格 → collapsible phase 节，默认折叠完成项

**用户拍板**：4. **从断点重来**，**其它按推荐**。
**用户说明**：「保存」=用户点「保存项目」按钮，那刻才把缓存变成正式项目卡片。当前项目产物需要暴露（debug 阶段），后期产品迭代再决定是否隐藏。

---

## Q9 — 完整度判定 — 算法 / 阈值 / 错判代价 / 用户兜底

**不对称代价**：
- oneline 误判成 prd → 跳过主策划 → 系统策划拿模糊一句话拆任务 → 输出质量崩（**重**）
- prd 误判成 oneline → 主策划再设计一遍 → 可能加噪音，但通常无大害（**轻**）

→ 阈值应偏保守倾向 "oneline"。

4 个子决策：
- 9.1 判定算法 → A 字数 / B LLM 二分类 / C 复合
- 9.2 LLM 二分类 prompt 草稿（5-shot 例子）
- 9.3 是否输出 confidence/reason？→ A 仅标签 / B 加 reason / A+B
- 9.4 是否手动覆写？→ A 不给 / B 下拉 / C 失败后才显示

**用户拍板**：1.B（LLM 二分类）/ 2.可以（接受 prompt 草稿）/ 3.A（仅标签）/ 4.A（不给手动覆写）

**用户说明**：「当前用户对 AI 产品的容错耐心较足，但对复杂的 UI 交互方案不耐受，故如此设计。」

→ **这是个值得做默认值的产品决策原则**。

---

## Q10 — 老 create_new + 自愈机制 + iterate_existing 怎么退役 / 演进？

6 个子决策：
- 10.1 老 create_new → A 直接覆盖（Git history 留作回退）
- 10.2 iterate_existing → A 本轮不动，下一轮按同模式重写
- 10.3 clarify/modify/abort 三条线 → 不变
- 10.4 router 和 intent_classifier → 不变
- 10.5 后端 API → 加 4 个 endpoint（pm_state / pm_save / pm_restart / pm_cancel）
- 10.6 测试覆盖 → 仅 smoke test，细单测稳定 2-3 周后再补

**用户拍板**：**全部按推荐**。

---

## Grill 总结

**最大架构决策（3 个）**：

1. **每 phase 一个独立提交工具 + Pydantic args_schema** — 把"emit_output 风格的模糊 payload dict"问题彻底治掉。
2. **草稿全程 in-memory，「保存」才入库** — 修了用户提到的"现有系统问题"。drawer 关了不死、新建对话才丢、关程序自然消亡。
3. **失败时「从断点重来」单按钮** — 不重跑 Phase 1-2 浪费 token，只重跑挂掉的那个 phase 起。

**最有价值的产品决策原则**：

> 用户对 AI 容错耐心 > 对复杂 UI 的耐心。

→ 后续凡是"加按钮让用户选" vs "让 LLM 自己决定"的设计冲突，**默认选后者**。

**关键技术债**：

- iterate_existing 仍是老 3-工具串调，遇到同类问题会复现。下一轮按同模式重写。
- 当前没有 PM 工作流的完整单测。本轮只 smoke test。
