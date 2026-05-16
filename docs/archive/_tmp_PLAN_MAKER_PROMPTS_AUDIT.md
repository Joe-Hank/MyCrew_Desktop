# Plan Maker 提示词全量审计 — 用于性能优化讨论

> ⚠️ 临时文档，优化定方案后可删除
> 日期：2026-05-15（已应用 3 项优化 + 用户决定重新设计整套提示词）
> 状态：**3 项节省 8-10k tokens/轮已落地（commit `1814ca5`）**；
> **方案 B 工具合并 + Prefix caching 暂停**（等用户重新设计提示词）

---

## 总览（当前实际值，已应用优化）

```
┌─────────────────────────────────────────────────────┐
│ 1. System prompt = Goal + 渲染后的 Backstory         │  ~1800 tokens
│    (was ~2500 ↓ -700)                                │
├─────────────────────────────────────────────────────┤
│ 2. Task description = ID + 历史 + 用户最新输入        │  ~500-1500 tokens
│    (was ~1000-3000 ↓ -500~1500 for long sessions)   │
├─────────────────────────────────────────────────────┤
│ 3. Tool definitions (CrewAI 自动生成)                │  ~1500-2000 tokens
│    (unchanged — 待方案 B)                            │
├─────────────────────────────────────────────────────┤
│ 4. Expected output 字符串                            │  ~60 tokens
└─────────────────────────────────────────────────────┘
                              合计 ≈ 3800-5400 tokens (was 5000-7500)

× CrewAI max_iter = 5
≈ 一轮 Plan Maker 19-27k tokens (was 25-35k) ≈ 节省 25-30%
```

---

## 1. PLAN_MAKER_GOAL（当前值）

`backend/bootstrap/seed_plan_maker.py:28-31` —— 约 68 字符 ≈ 35 tokens
（原 ~135 字符，省 50%）

```
MyCrew Plan Maker：把用户的项目设计需求拆成可执行任务流并持久化。
架构规划归你（不拆给后置 PM）。非项目话题礼貌拒绝。
```

---

## 2. PLAN_MAKER_BACKSTORY_TEMPLATE（当前值）

`backend/bootstrap/seed_plan_maker.py:33-100` —— 约 1769 字符 ≈ 900 tokens
（原 ~2100 字符，省 15%）

含 3 个占位符 `{mode_context}` / `{available_mcp_servers}` / `{available_agents}`

```
## 上下文
{mode_context}

## 可用 MCP
{available_mcp_servers}

## 可用 Agent（已按模板筛选）
{available_agents}

## 硬约束
- 你独自做架构规划。**禁止**创建/调用任何含 "Project Manager / 项目经理 / PM"
  的执行 Agent；架构思考写进 architecture.md
- 每个非 final_qa 任务的 output_schema 必须含 `file_path`（项目相对路径）
  + 可选 `summary`。**禁止 description-only schema**（无 file_path = 拒收）
- file_path 一律用相对路径（与 root_path 设置时机解耦）；执行端 workspace
  工具自动拼绝对路径
- emit_output **会校验** file_path 真实存在，骗不过去
- task detail 必须明文指令执行 Agent："先用 write_file/unity_write_file/
  comfy_enqueue_workflow 把文件创建到 <相对路径>，再调 emit_output 报告路径"

## 编排
- 任务数 1-2→sequential，3-5→crew，6+→flow
- 末尾必须 kind="final_qa"，deps 指向所有终端节点
- output_schema 是合法 JSON Schema；`{}` 表示自由文本

## 默认技术栈
游戏/3D/VR/AR/交互 → **Unity 2022 LTS + C# + URP + Input System + UGUI**
（禁默认 Web/Python 游戏栈，除非用户明确指定）。
美术建模走 Blender MCP；图像生成走 ComfyUI MCP。

## 模式分流
- **create + Unity 模板**：按模板目录骨架设计完整子系统
- **create + 空模板**：暂仍按 Unity 思路，architecture.md 标注"类型可能非 Unity"
- **iterate（补丁模式，重要）**：
  1. 单轮任务 ≤ 5，每个任务改一个聚焦点
  2. 每个改动任务后紧跟**验证任务**（read 关键文件确认未破坏旧功能）
  3. architecture.md 顶部写本轮目标 + 涉及文件列表
  4. 修改前 read_file_local 查原内容；保留 .bak 或仅 patch 关键段
  5. 验证失败 → **后续任务停止**，让 QA 收尾报告
  6. 默认 modify 现有文件，不新建

## 何时澄清
默认直接产出（俄罗斯方块/Snake 等著名原型按合理默认假设立即调工具）。
只在输入极度抽象（"做个项目"）时提 1 个澄清问题。

## 范围限制
非项目设计请求 → 不调工具，回复：「（不在项目立项范围）— 我只能帮你拆解
项目任务。请描述具体项目，如『做一个 Unity 平台跳跃游戏，三关，每关有 boss』」

## 工具调用（严格按序，3 步）
方案明确时**必须依次调**：
1. `create_workflow(name, execution_kind, tasks)` — 持久化
2. `assign_agents(assignments)` — `existing_agent_id` 复用 / `new_agent{role,goal,backstory}` 新建（role 例: "Unity 客户端工程师"）
3. `write_blueprint(architecture_overview, tasks)` — 写 `<root>/.mycrew/`；tasks 与 step 1 同结构，但每项多一个 `acceptance_notes`（"怎么验证算 OK"）

调完 3 步立刻**一句中文**收尾（例: "任务方案已生成，N 个 task，新建 M 个 agent"），
不再列任务、不重复、不思考下一步、不输出 ```json 块。
```

---

## 3. 占位符运行时填入（render_plan_maker_backstory）

`backend/bootstrap/seed_plan_maker.py:255-405`

### 3.1 `{available_mcp_servers}`
DB 里所有 `enabled=1` 的 MCP 一行一个。当前 7 个：
```
- blender
- comfyui
- figma
- git
- notion
- tavily
- unity
```
≈ 70 字符 ≈ 35 tokens

### 3.2 `{available_agents}` ✅ 已优化
**旧**：16 个全列，~600 tokens
**新**：按 `template_id` 关键词筛选 + QA 角色必保留 + cap 8 个，~250 tokens

逻辑（`_filter_agents_for_prompt`）：
- 创建模式（有 template_id）：按 `_TEMPLATE_AGENT_KEYWORDS[template_id]` 关键词与 agent role/goal 匹配打分，取 top 8
- 迭代/空模板：前 8 个（不筛选）
- QA Engineer / Reviewer 类必保留（无视分数）
- 末尾加提示："如需其它角色请调 list_agents 工具"

模板 → 关键词映射：
```python
"unity_universal_2d":  unity, 2d, sprite, platformer, ui, ux, narrative, art, concept, audio, system, qa
"unity_universal_3d":  unity, 3d, model, shader, art, concept, vfx, animator, audio, system, qa
"unity_ar_mobile":     unity, ar, xr, 3d, model, ui, ux, shader, qa, art
"unity_mr_core":       unity, mr, xr, 3d, model, ui, ux, shader, qa, art
"blank":               ()  # 不筛选，全部展示
```

### 3.3 `{mode_context}`
不变。
- 创建 + Unity 模板：~300-500 tokens
- 创建 + blank：~80 tokens
- 迭代：~350 tokens

---

## 4. Task description（每轮拼接的用户消息）✅ 已优化

`inception_svc.py:673-679` + `_format_history_for_task` (line 856)

```python
description = (
    f"## 当前会话 ID\n{session_id}\n\n"
    f"## 对话历史\n{history}\n\n"
    f"## 用户最新输入\n{content}\n\n"
    "请：(1) 用自然语言回复用户；(2) 当方案明确时调用 create_workflow 工具持久化。"
)
```

### history 新策略（首条 + 末 4）
- 总消息 ≤ 5 条 → 全量保留
- 总消息 > 5 条 → 保留首条（用户原始项目需求）+ 末 4 条 + 中间用一行 gap 标记
- 例：12 条消息时
  ```
  [用户] 做个 Unity 2D 平台跳跃，三关
  …（中间 7 条消息已省略）…
  [Plan Maker] 任务方案已生成...
  [用户] 加个 boss 战
  [Plan Maker] 已追加 boss 战任务...
  [用户] 把 BGM 改成赛博朋克风格
  ```

**典型节省**：长会话从 ~2000 tokens 降到 ~500-800 tokens，**省 1000-1500 tokens / 轮**

---

## 5. Tool definitions（CrewAI 自动生成）— 未变

3 个工具的 JSON Schema：
- `create_workflow`: ~250 tokens
- `assign_agents`: ~300 tokens
- `write_blueprint`: ~300 tokens
- 迭代模式额外 `read_file_local` + `list_directory_local`: ~200 tokens

**总计 ~1500-2000 tokens**，待方案 B 处理。

---

## 6. Expected output 字符串 ✅ 已修 bug

`inception_svc.py:729-732`

**旧**：`"依次调用 create_workflow + assign_agents 两个工具..."` （错，缺 write_blueprint）
**新**：`"依次调 create_workflow + assign_agents + write_blueprint 三个工具，然后用一句中文确认收尾。"`

---

## 7. QA 任务的强制 detail

`create_workflow.py:57-69` — 不在 Plan Maker context 里，但 create_workflow 调成功后会强制覆盖 final_qa 任务的 detail。**未变**。

---

## 8. 优化进度跟踪

| # | 优化 | 状态 | 节省 / 轮 | 备注 |
|---|---|---|---|---|
| 1 | 历史窗口：首条 + 末 4 | ✅ **已做** | 1000-1500 tokens (长会话) | commit `1814ca5` |
| 2 | Agent 列表按模板过滤 + cap 8 | ✅ **已做** | ~400 tokens | commit `1814ca5` |
| 3 | Backstory 去重压缩 | ✅ **已做** | ~200 tokens + Goal -50% | commit `1814ca5` |
| 4 | 修 expected_output 工具数 | ✅ **已做** | (语义正确) | commit `1814ca5` |
| 5 | 方案 B：write_blueprint 合并进 create_workflow | ⏸️ **暂停** | ~6000 tokens（潜在） | 用户要重新设计整套提示词，先停 |
| 6 | Prefix caching（LLM 端） | ⏸️ **暂停** | 60-70% 计费 tokens | 同上 |
| 7 | 拆 Plan Maker 为多 Agent | 📋 未做 | 不确定 | 长期方案 |

**当前一轮 Plan Maker 节省**：~8-10k tokens（5 iter 累计），约 **25-30%** 减少。

---

## 9. 用户接下来做什么

用户决定**整体重新设计提示词**（不再走渐进优化路径）。当前文档作为：
1. 现状基线（看完整结构 + 各部分占用）
2. 重新设计时的字段约定（保留 `{mode_context}` / `{available_mcp_servers}` / `{available_agents}` 占位符即可，渲染逻辑无需改）
3. 重新设计后参考"硬约束"那 5 条 + "工具调用按序"那 3 步是必须保留的语义

用户写完新版后给我，我帮：
- 落地到 `seed_plan_maker.py` 的 GOAL + BACKSTORY_TEMPLATE
- 启动后会自动通过 `_prompt_version_hash` 检测变化，DB 里 Plan Maker agent 行自动更新
- 删除本文件（或保留作历史档案）

---

> 文件路径：`docs/_tmp_PLAN_MAKER_PROMPTS_AUDIT.md`
> 用户完成提示词重新设计后可删
