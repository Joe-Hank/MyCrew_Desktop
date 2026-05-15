# PM 工作流 v3 — create_new 5-phase Crew + Cache-First 持久化

## Context

### 起因
赛博朋克跳跃求生项目里多个 task 卡在 `'file_path' is a required property` 的 validation_failed。诊断显示根因是 Plan Maker 的 task detail 没注入「调 emit_output」指令，agent 写了文件但没汇报路径。

这只是冰山一角。当前 PM 是「一次 kickoff + 3 工具串调」的整体，硬约束很多但完全无校验；Unity 这种复杂场景下 LLM 临时忘掉规则的概率不可忽视。

需要把 PM 从「一次性出整张蓝图」改成「分阶段、强契约、可观测、可控」的 5-phase Crew。**当前先做 Unity 专项**；后期通过创建项目页加一层「项目类型」筛选支持别的栈，但本轮不做。

### 总规约（贯穿所有决策）
- **高度可控** — 每 phase 独立、可单独重跑、可单独 debug
- **模块化** — 5 个 phase 各自一个文件、一个工具、一个 Pydantic 契约
- **透明化** — 所有中间产物可见、所有失败原因显式
- **用户容错耐心 > UI 复杂度** — 宁可让 LLM 自己解决、不加复杂操作按钮

### 设计决策汇总（10 轮 grill 后定）
| # | 决策点 | 选项 |
|---|---|---|
| Q1 | Inter-phase 数据传递 | 强类型 Pydantic + 代码层校验（B） |
| Q2 | 5 个 phase 怎么交付物 | 各配独立 submit_xxx 工具，args_schema 严格 |
| Q3 | 失败处理 | 3 层防御：self-correct → 焦点修复 → 单按钮「从断点重来」 |
| Q4 | mkdir 任务时机 | 真 task（execution-time），因 PM 时 root_path 未绑 |
| Q5 | mkdir 任务 agent | seeded singleton「项目初始化助手」+ builtin mkdir 工具 + 显式 deps=[0] |
| Q6 | 草稿缓存 | 后端 in-memory dict、HTTP 保持 blocked、drawer mount-keep |
| Q7 | 取消语义 | Stop = 真取消 task；新会话 = cancel + clear；关程序 = 自然消亡 |
| Q8 | 调试日志 | 单事件 `pm.log` + phase 字段 + payload 截短；保存时 dump 完整 trace |
| Q9 | 完整度判定 | cheap LLM 二分类，仅输出 ONELINE/PRD 标签，无手动覆写 |
| Q10 | 退役策略 | 直接覆盖老 create_new；iterate_existing 本轮不动；仅 smoke test |

---

## 5-Phase Crew 流程

```
用户消息 → router → intent_classifier=create_new → 新 sub_agent
                                                     │
   ┌─────────────────────────────────────────────────┘
   ▼
[Phase 0] 完整度判定                        cheap LLM, t=0, max_tokens=10
   ├─ 输入：user_message
   └─ 输出：Literal["ONELINE", "PRD"]
   │
   ▼ 若 PRD，跳过 Phase 1
[Phase 1] 游戏主策划                        pro LLM, t=0.7
   ├─ 工具：submit_concept(concept: ConceptDoc)
   ├─ 输入：user_message + 模板 context
   └─ 输出：ConceptDoc { title, core_loop, systems[], mechanics[], art_style, target_player }
   │
   ▼
[Phase 2] 系统策划                          pro LLM, t=0.5
   ├─ 工具：submit_atomic_tasks(tasks: list[AtomicTask])
   ├─ 输入：concept（或 user_message，PRD 路径）+ 模板 context
   └─ 输出：list[AtomicTask] { title, detail, deps[], kind, est_complexity }
   │       — 此阶段允许小缺陷，审核策划负责修
   │
   ▼
[Phase 3] 审核策划                          pro LLM, t=0.2
   ├─ 工具：submit_reviewed_tasks(tasks: list[ReviewedTask])
   ├─ 输入：原子任务列表 + concept
   └─ 输出：list[ReviewedTask]（AtomicTask 超集 + acceptance_notes + input_sources + output_schema）
   │
   ▼
[Phase 4] 项目管理                          pro LLM, t=0.3
   ├─ 工具：submit_pathed_tasks(setup_task: PathedTask, tasks: list[PathedTask])
   ├─ 输入：审核任务列表 + unity_templates.render_template_context(template_id)
   ├─ 行为：
   │    1. 给每个任务推导 output_paths（基于模板目录骨架）
   │    2. 构造 index-0 setup task（kind="setup", deps=[], agent_id=seeded 项目初始化助手）
   │    3. 给所有 regular/final_qa task 的 deps 加上 0
   └─ 输出：list[PathedTask]（ReviewedTask 超集 + output_paths）
   │
   ▼
[Phase 5] Agent 指挥员                      pro LLM, t=0.2
   ├─ 工具：submit_assignments(assignments: list[Assignment])
   ├─ 输入：含 output_paths 的任务表 + 全部 agents 列表 + 工具清单
   ├─ 行为：跳过 setup task（已 pre-assigned），给其余任务匹配 agent
   └─ 输出：list[Assignment] { task_index, agent_id, reason }
   │
   ▼
[Cache-Ready 状态]
   - 全部产物落到 inception_svc._session_drafts[sid]
   - NOT 入 DB / NOT 写 .mycrew/
   - 前端右侧从 debug log 切到蓝图编辑器
   - 显示「保存项目」按钮
   │
   ▼ 用户点保存
[Persist]
   - 写 .mycrew_pending/ → DB → mv 到 root_path/.mycrew/
   - 设 session.project_id
   - 清 _session_drafts[sid]
   - dump debug_log_full 到 .mycrew/_planner_trace.json
   - 广播 inception.workflow_created
```

---

## Pydantic 契约（progressive enrichment）

```python
# backend/agents/sub_agents/_planner_models.py

class ConceptDoc(BaseModel):
    title: str
    core_loop: str           # 一段话讲清楚核心循环
    systems: list[str]       # 系统名字列表（如"跳跃系统/敌人 AI/关卡进度"）
    mechanics: list[str]     # 具体机制（如"双跳/慢动作/连击 combo"）
    art_style: str           # 美术风格关键词
    target_player: str       # 目标玩家描述

class AtomicTask(BaseModel):              # Phase 2 系统策划输出
    title: str
    detail: str
    deps: list[int] = []                  # 0-based index 引用本列表
    kind: Literal["regular", "final_qa"] = "regular"
    est_complexity: Literal["small", "medium", "large"] = "medium"

class ReviewedTask(AtomicTask):           # Phase 3 审核策划补充
    acceptance_notes: str                  # 验收标准（QA agent 读这个）
    input_sources: list[str] = []          # 自然语言描述本任务依赖的信息源
    output_schema: dict                    # JSON Schema，必须含 file_path 字段

class PathedTask(ReviewedTask):           # Phase 4 项管补充
    output_paths: list[str]                # 推导的相对路径（用于 mkdir）
    kind: Literal["regular", "final_qa", "setup"] = "regular"  # 扩展 setup
    agent_id: str | None = None            # setup 任务在 phase 4 pre-assigned

class Assignment(BaseModel):              # Phase 5 输出
    task_index: int
    agent_id: str
    reason: str                            # 一句话解释为什么是这个 agent
```

---

## 文件改动

### 新增
| 文件 | 内容 | 估计行数 |
|---|---|---|
| `backend/agents/sub_agents/_planner_models.py` | 5 个 Pydantic 模型 + 工具 args schemas | 150 |
| `backend/agents/sub_agents/_planner_tools.py` | 5 个 submit_xxx 工具工厂（仿 emit_output） | 250 |
| `backend/agents/sub_agents/_planner_orchestrator.py` | 5 phase 串接 + 状态机 + 焦点修复 | 400 |
| `backend/agents/sub_agents/_planner_prompts.py` | 5 个 phase 的 prompts（含主策划 / 系统策划 / 审核 / 项管 / 指挥员） | 300 |
| `backend/services/planner_cache_svc.py` | `_session_drafts` 容器 + 增删查 | 100 |
| `backend/services/planner_persist_svc.py` | `finalize_to_project(sid)` — pending → DB → .mycrew | 150 |
| `backend/bootstrap/seed_planner_agents.py` | seed「项目初始化助手」+ 写入 agents 表 | 50 |
| `frontend/src/components/inception/PMDebugLog.tsx` | 右侧 debug log 组件 | 200 |
| `frontend/src/hooks/usePmState.ts` | 拿 + 监听 pm_state 的 hook | 80 |
| `backend/api/routes_pm.py` | 4 个新 endpoint（pm_state / save / restart / cancel） | 100 |

### 改写
- `backend/agents/sub_agents/create_new.py` — 重写为入口，调 `_planner_orchestrator.run_crew()`
- `backend/src/tools/builtin/local/_output_capture.py` — 加 `set_planner_output(sid, phase, payload)` / `pop_planner_output(sid, phase)`
- `frontend/src/components/inception/InceptionDrawer.tsx` — 关闭时改为 `display:none`（mount-keep）+ 接入 PMDebugLog + 调用新 4 个 API
- `frontend/src/stores/useInceptionStore.ts` — 加 pm_state 字段

### 不动
- router / intent_classifier
- compliance_gate / clarify_design / modify_blueprint / abort_or_restart
- iterate_existing（下一轮按同模式重写，本轮加 TODO 注释）
- 现有 3 个工具（create_workflow / assign_agents / write_blueprint）— 新流程不调，但 iterate_existing 还在用，留着
- write_blueprint 的 `_do` 写盘逻辑 — 抽公共函数 `write_blueprint_to_disk()` 到 services 层，老 tool + 新 persist_svc 共用

---

## 关键复用

| 复用 | 来源 |
|---|---|
| 工具校验 + 失败重试 + capture 模式 | [emit_output.py:_run](backend/src/tools/builtin/local/emit_output.py#L95) 整套复制 5 份 |
| 模板上下文渲染 | [unity_templates.render_template_context](backend/data/unity_templates.py#L192) |
| LLM 三档分层 | [agents/_llm_picker.pick_llm](backend/agents/_llm_picker.py) |
| CrewAI Agent 构造 | [_base.run_crewai_agent](backend/agents/sub_agents/_base.py#L57) — 每 phase 调一次 |
| 焦点修复 kickoff | [create_new.py:_repair_step2/3](backend/agents/sub_agents/create_new.py) 抽象成 `run_focused_phase_kickoff()` |
| WS 广播 | [api.ws.manager.broadcast](backend/api/ws.py) — 新事件 `pm.log` |

---

## 实施分阶段

| 阶段 | 内容 | 验证 |
|---|---|---|
| **A** | Pydantic 模型 + 5 个 submit 工具 + capture | unit test mock — 各工具喂数据验证校验逻辑 |
| **B** | seed「项目初始化助手」+ persist_svc 抽公共写盘函数 | DB 里有这个 agent；老 iterate_existing 流程不破 |
| **C** | 完整度判定 + Phase 1（主策划） + Phase 2（系统策划） + orchestrator 骨架 | 喂"做个 Tetris"跑通到 Phase 2，看产出 |
| **D** | Phase 3（审核） + Phase 4（项管） + Phase 5（指挥员） | 跑通到 Phase 5，看完整草稿 |
| **E** | cache_svc + pm_state + pm_cancel + pm_restart endpoint | curl 验证 |
| **F** | 前端 PMDebugLog + InceptionDrawer mount-keep + 接入新 API | 跑 Tetris 端到端看右侧实时 log |
| **G** | 「保存项目」按钮 → persist_svc → DB + .mycrew/ | 保存后首页看到项目卡 |
| **H** | 「断点重来」按钮 + 失败路径覆盖 | 故意让 Phase 3 抛错，验证按钮可见 + 按下从 Phase 3 重跑 |
| **I** | 整端到端跑 cyberpunk 重新 → 验证 `'file_path' is required` 类问题不再出现 | 真实 LLM 跑 1 次 |

每阶段独立 commit。**A-B** 是底层，纯后端不可见；**C-D** 是 PM 算法骨架；**E** 是 API 层；**F-G-H** 是前端体验；**I** 是验收。

---

## 验证

### 自动化（smoke test，本轮唯一硬要求）
```python
# tests/integration/test_planner_crew.py
async def test_create_new_crew_oneline_path(monkeypatch):
    # mock 5 个 LLM 返回固定 JSON
    # 跑 "做个 Tetris"
    # 期望 _session_drafts[sid].status == "ready"
    # 期望 5 phase 全出现在 debug_log
    # 期望 draft_blueprint 含 7 个 tasks（mkdir + 5 + final_qa）
```

不写细粒度单测 — 等架构稳定 2-3 周后再补。

### 手测（每实施阶段后）
1. **Tetris 创建**（oneline 路径）→ 跑通 → 保存 → 首页看到项目卡
2. **完整 PRD 创建** → 跳过 Phase 1 → 跑通
3. **关 drawer 中途 + 重开** → 状态恢复 → debug log 连续
4. **新建对话** → 老草稿丢失
5. **Phase 3 故意挂**（hack 一个 prompt 返回非法 JSON）→ 「从断点重来」按钮可见 → 按下从 Phase 3 重跑

### 回归
- 老 iterate_existing 流程仍能跑（创建带 root 的项目 → 迭代 → 出新 .mycrew/iter-NNN/）
- modify_blueprint / clarify_design / abort_or_restart 三条线不受影响

---

## 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| 5 phase 串接耗时 60-120s，用户耐心不够 | debug log 持续更新让用户有反馈；UI 限制不让重发 |
| Token 成本 ~3x | 完整度判定走 cheap；只有 Phase 1-5 走 pro；不重要 phase 可降到 cheap 后期调 |
| LLM 输出违反 Pydantic schema | submit 工具内置校验 + 失败原因返回让 LLM 自纠（最多 max_iter=5 次） |
| Phase 4 推路径与 Unity 模板不一致 | 项管 prompt 强制读 directory_skeleton；output_paths 加路径前缀校验 |
| 后端进程崩溃 / 内存草稿丢失 | 接受这个语义（用户已说"关程序删缓存"）；前端崩溃恢复指引 |
| 5 phase 中某 phase 永不通过 schema 校验 | max_iter=5 → 焦点修复 1 次 → 失败显示「从断点重来」按钮 |
| iterate_existing 还在用老 3-工具串调，会继续遇到老问题 | 注释打 TODO；下一轮按同模式重写 |

---

## 不在本轮

- iterate_existing 重写
- 其他项目类型（Web/数据脚本/CLI）的专项 5-phase
- 完整单测覆盖（仅 smoke）
- A/B 灰度切换（直接全量替换）
- 项目类型选择器 UI（创建项目页加一层筛选）

---

## 提交节奏

预计 9 个 commit（A-I 各一个）。每个独立提交、独立验证。**完成时间约 1-2 天工作量**（不含真实 LLM 调试调优）。
