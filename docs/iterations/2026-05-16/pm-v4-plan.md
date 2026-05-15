# PM v4 — Crew-Native Execution + 预设 Performer Pool + 画布展开

## Context

### 起因
霓虹攀升项目的 task 9（美术资产生成）暴露**两层 bug**：

1. **emit_output 校验漏洞**：`_PATH_FIELD_NAMES` 列了 `file_path`（单数）但漏了 `file_paths`（复数）→ agent 提交 9 个声称的 sprite/prefab 路径，emit_output 静默通过（0 个待验路径）→ 磁盘上**全空**，task 状态却是 done。
2. **任务流架构错配**：复杂产出（图、模型、动画）需要**多 agent 顺序协作**（Designer → Producer → Integrator → QA），但 Phase 5 只能派 1 个 agent。结果：Phase 5 派"Concept Artist"做"生 sprite"任务 → agent 按 reference 思路写计划而非真生图 → emit_output bug 加持，假产出过关。

更广义的问题：当前 27 个 agent 里，**9 个是 Phase 5 auto-gen 的"Unity 工程师变体"**，工具贫乏（只有通用 5 件套，没挂 Unity MCP）；**3 个 PM 类 agent 已废**（Plan Maker / Project Manager / Project Structure Manager —— PM v3 流程已替代）。

→ 这是 PM v4：**Crew-Native 执行 + 预设 Performer Pool + 画布可视化升级**。

### 用户已拍板的决策

| # | 决策 |
|---|---|
| Phase 5 不再创建新 performer | 全部预设 + 标注 applicable_scenarios，Phase 5 LLM 只从菜单选 |
| Agent 单一职责原则 | 一个 agent 做一件事；需要多步 → Crew |
| Audio | 8-bit 程序化合成（自建 builtin tool），暂不接 AudioCraft |
| 删除 | Plan Maker / Project Manager / Project Structure Manager / 9 个 auto-gen Unity 工程师 |
| Audio Designer | 转岗为 Audio Crew 的 Head（不独立存在） |
| Technical Artist | 保留 + 优化（加 Unity MCP 资产工具集，目前只有 git） |
| Narrative Designer | 保留（叙事专用单 agent） |
| Crew DB schema | 按需求选 JSON 字段（agent_sequence）vs 关联表 — 我推 JSON |
| Crew 任务 emit_output | 只由 QA sub-agent 最后调用 |
| sub_step WS 事件 | 加 — 用于子卡片实时高亮 |
| 任务卡片尺寸 | +20%（约 200 → 240px） |
| Crew 展开布局 | 自动平移下游（B） |
| Crew 子卡片 — Head | 保留完整动作（编辑 / 暂停 / 重试 / 对话 / IO 查看）+ 配套存储 |
| Crew 子卡片 — Executor & QA | 只读，仅「对话」「IO 查看」 |
| 项目尾部 final_qa | 保留，但**职责变窄**为跨 task 集成验收（场景能加载、Prefab 引用脚本存在、无编译错误）。每个 Crew 内部 QA 负责自家 task 内产物验收 |
| QA 验收标准的来源 | **PM 输出的 JSON**（task.output_paths / task.acceptance_notes / task.output_schema）。Head agent **不允许**修改产出数量与位置 — Head 只精化"怎么做"，不决策"做什么" |
| 创建新 agent 工具 | Phase 5 submit_assignments 工具**不含** new_agent 字段。LLM 只能从预设池选 performer (agent 或 Crew)，不能创造 |

---

## 设计

### 架构改造一览

```
PM v3 输出（Phase 5.assignments）：
    [{task_index, agent_id, reason}, ...]
                ↓ 升级
PM v4 输出：
    [{task_index, performer_ref: {kind: "agent" | "crew", id}, reason}, ...]

workflow_svc 执行任务：
  performer.kind == "agent"  →  调 1 个 CrewAI Agent（现状）
  performer.kind == "crew"   →  调 CrewAI Process.sequential，
                                   N 个 Agent 串行执行
                                   每个 Agent 拿 step_instructions + 上一步 output
                                   最后 QA Agent 调 emit_output 提交聚合产物
```

### 两层 QA 模型（重要约定）

PM v4 有**两个 QA 层级**，职责互补：

| 层 | 谁 | 范围 | 验收标准来源 |
|---|---|---|---|
| **Crew 内 QA**（每个产物 Crew 的最后一步） | Crew.agent_sequence 最后一个 QA agent | 本 task 自己的产物 | task.output_paths（PM 给）+ task.output_schema（PM 给）+ task.acceptance_notes（PM 给） |
| **项目尾 final_qa**（独立 task） | 单独的 QA agent 任务（非 Crew） | **跨 task 集成**：场景是否能加载、Prefab 引用的脚本是否存在、是否有编译错误、整个项目能否打开 | 项目级 invariant（编译通过 / 主场景可加载 / 无 Missing Reference） |

**关键约定**：

- Crew 内 QA **不参考 Head 的输出**作为验收标准 — Head 只精化"怎么做"，标准是 PM 在 phase 3/4 已经定好的契约
- 项目尾 final_qa 用 Unity MCP 的 `manage_editor` (Refresh + 检查 console) + `read_console` (拿编译错误) 做集成测
- 两层 QA 各自验收，互不替代。Crew QA 不通过 → task validation_failed；final_qa 不通过 → project completed_with_issues

### final_qa 失败后的处理（新加，MVP 走"报告 + 引导迭代"）

不做自动修复（auto-fix Crew 风险太高 — 编译错可能是设计问题，agent 改错会越改越烂）。改做**两段式**：

**段 1 — 报告**（final_qa 内部直接做）：
- final_qa agent 用 manage_editor + read_console 拿到所有 issue
- 调 emit_output 提交 `{verdict: "fail"|"warn", issues: [{kind, file, line, message, suggestion}]}`
- 同时写一份 markdown `<root>/.mycrew/_final_qa_report.md` 给人看
- 项目状态 → `completed_with_issues`

**段 2 — 迭代修复（按钮触发，不自动）**：
- 首页项目卡片的「迭代」按钮（已存在）走 iterate 模式
- 进入 Plan Maker drawer 时**自动把 `_final_qa_report.md` 注入到对话框**作为预填消息
- 用户可以编辑/删减后回车 → PM v3 iterate 流程拿这些 issues 当输入 → 产出新一轮修复 task 列表

→ 不引入 "Fix Crew" 等自动化路径。用户保留掌控权。

> 为什么不上自动修复 Crew：
> - 编译错经常需要跨多个文件改、改设计；交给一个 agent 没把握
> - 自动改容易把"半完成"的项目变成"看上去完成但更乱"
> - 用户从 issue 报告自己读 5 分钟再点迭代，质量好得多

### Crew DB schema（用现有 `crews` 表 + 扩字段）

```sql
-- 加列（migration）
ALTER TABLE crews ADD COLUMN applicable_scenarios TEXT;
ALTER TABLE crews ADD COLUMN agent_sequence TEXT;  -- JSON
```

`agent_sequence` JSON 结构 + 各 Crew 的 step_instructions 都直接写定（弹性留在"具体参数"层，职责边界不动）：

```json
[
  { "role": "head",     "agent_id": "<id>", "step_instructions": "<见下>" },
  { "role": "executor", "agent_id": "<id>", "step_instructions": "<见下>" },
  { "role": "qa",       "agent_id": "<id>", "step_instructions": "<见下>" }
]
```

**通用职责约束**（所有 step_instructions 共同前缀）：

> 你接到的 task 已经经过 PM 4 个阶段完整规划。
> `task.output_paths`（必产文件路径列表）+ `task.output_schema`（产物字段约束）+ `task.acceptance_notes`（验收标准）**全部已定**。
> 你**不允许**增删 task.output_paths、不允许修改 schema、不允许重新决定产物数量/位置。
> 你只在 PM 已给定的契约内做你这一步该做的事。

### 8 个 Crew 的 step_instructions

#### Art Crew

```
Head — Art Director:
  把 task.output_paths 里的每一项转化为"产物执行规格"，包含：
    - 分辨率（如 64x64 / 256x256，按 task.detail 推断或默认 64x64）
    - 风格关键词 + 配色码（基于 task.detail 中的风格线索）
    - 命名差异点（多个 sprite 的语义区分）
  调 emit_output 提交 spec dict，供下游使用。

Executor 1 — Concept Artist:
  基于 Head 的 spec + task.output_paths 清单，用 ComfyUI 出"风格参考图"作为视觉锚点。
  生成路径放 `<project>/output/_crew_cache/<task_id>/concept_*.png`（不入 task.output_paths）。
  不要直接生成最终资产。
  调 emit_output 报告 reference 路径列表。

Executor 2 — ComfyUI Image Generator:
  对 task.output_paths 中**每一个**目标路径，调 comfy_create_workflow_from_template +
  comfy_enqueue_workflow 真生 PNG，参数取 Head 的 spec、视觉参考 Executor 1 的 reference。
  严禁用 write_file 写空 png 占位。
  调 emit_output(file_paths=[全部 task.output_paths]) 报告。

Executor 3 — Technical Artist:
  对每个 PNG：调 manage_asset 设置 TextureType=Sprite + 配 pixel-per-unit；
  task.detail 暗示是 sprite sheet 时用 manage_texture 切片。
  不修改路径/文件名。
  调 emit_output 报告 import status。

QA — QA Engineer:
  对照 PM 契约验收：
    1. task.output_paths 每个文件存在且 size > 0（list_directory_local + read_file_local 抽样）
    2. 是合法 PNG（首 8 字节是 PNG signature）
    3. 同名 .meta 文件已生成
  不参考 Head spec 作为补充验收。
  调 emit_output({verdict, file_paths, issues, summary})。
```

#### 3D Asset Crew

```
Head — Art Director:
  把 task.output_paths（.fbx / .blend / .obj）转化为 3D 规格：
    - 多边形上限（按 task.detail 风格定，pixel art → 低面；写实 → 高面）
    - UV / 材质要求 / LOD 级数
    - 网格命名约定
  调 emit_output 提交 3D spec。

Executor 1 — 3D Modeler:
  按 spec 用 Blender MCP 建模（execute_blender_code + 各 polyhaven/rodin 辅助工具）。
  输出 .fbx 到 task.output_paths 中的对应路径。
  调 emit_output 报告产物文件路径 + 多边形数。

Executor 2 — Technical Artist:
  对每个 .fbx：用 manage_asset 配 Unity Model Importer（rig type / animation type / read/write enabled）；
  task.detail 提到 LOD → manage_asset 设置 LODGroup。
  调 emit_output 报告 Unity 导入 status。

QA — QA Engineer:
  对照 PM 契约：1) 文件存在 + 非空；2) .fbx 合法（首部 magic OK）；3) .meta 已生成。
  调 emit_output({verdict, ...})。
```

#### Animation Crew

```
Head — Art Director:
  把 task.output_paths（.anim / .controller）转化为动画规格：
    - 帧率（如 30fps / 60fps）
    - 关键动作列表（idle / walk / jump / attack 等）
    - 循环规则 + 过渡规则
  调 emit_output 提交动画 spec。

Executor 1 — 3D Modeler（rig 准备）:
  如 spec 需要骨骼绑定且无现成 rig：用 Blender MCP 给上游模型加 rig（armature + weight paint）。
  否则跳过（emit_output 报告"已有 rig 可用"）。

Executor 2 — Animator:
  按 spec 在 Blender 里制作动画关键帧 + 导出 .anim 或对应 Unity 格式到 task.output_paths。
  调 emit_output 报告。

Executor 3 — Technical Artist:
  对每个 .anim：用 manage_asset 配 AnimationClip import setting；
  必要时创建 AnimatorController 引用这些 clip（manage_asset create AnimatorController）。
  调 emit_output 报告。

QA — QA Engineer:
  对照 PM 契约验收文件存在 + 合法 + meta 齐全。调 emit_output。
```

#### VFX Crew

```
Head — Art Director:
  把 task.output_paths（VFX prefab / 粒子配置）转化为视觉规格：
    - 粒子数量上限（性能预算）
    - 颜色 / 材质 / 持续时间 / 触发逻辑
  调 emit_output 提交 VFX spec。

Executor 1 — VFX Artist:
  用 Blender / 内置工具创建必要的贴图/网格 → 输出到 _crew_cache，调 emit_output 报告路径。

Executor 2 — Technical Artist:
  用 Unity MCP 在 task.output_paths 处创建 ParticleSystem prefab：
    - manage_prefabs.create 新建空 prefab → manage_components.add 添加 ParticleSystem →
      manage_components.set_property 按 Head spec 配参数 → 关联 Executor 1 的贴图
  调 emit_output 报告 prefab 路径。

QA — QA Engineer:
  对照 PM 契约验收：prefab 文件存在 + 可加载（无 Missing reference）+ meta 齐全。
```

#### System Implementation Crew

```
Head — System Designer:
  把 task.output_paths（C# 脚本）转化为实现规格：
    - 类名 + namespace
    - public API 签名（方法 + 字段）
    - 状态机 / 数据结构细节
    - 关键算法步骤
  task.detail 已给业务语义；Head 把它细化到方法级别可执行。
  调 emit_output 提交 implementation spec。

Executor — Unity Developer:
  按 spec 用 Unity MCP（create_script 等）创建 .cs 文件到 task.output_paths。
  代码要：(1) 含 spec 列的方法和签名 (2) 通过 validate_script 校验 (3) 在 Unity refresh 后无编译错误。
  调 emit_output(file_paths=...) 报告。

QA — QA Engineer:
  对照 PM 契约：
    1. 每个 .cs 文件存在且包含 spec 要求的方法签名（find_in_file 或 read_file_local）
    2. validate_script 通过
    3. .meta 已生成
  调 emit_output({verdict, ...})。
```

#### UI Implementation Crew

```
Head — UI/UX Designer:
  把 task.output_paths（UI Prefab + UI 图片）转化为 UI 规格：
    - 布局描述（Canvas size / 锚点 / 层级）
    - 图片资源清单（每个 UI 元素一张图，分辨率定好）
    - 交互行为说明
  调 emit_output 提交 UI spec。

Executor 1 — ComfyUI Image Generator:
  对 task.output_paths 中的 UI 图片路径，按 Head spec 真生 PNG。
  调 emit_output 报告。

Executor 2 — Unity Developer:
  用 Unity MCP 创建 Canvas + UI 层级到 task.output_paths 中的 prefab 路径：
    manage_gameobject create Canvas → manage_components add Image/Text/Button →
    set_property 引用 Executor 1 生成的 png
  调 emit_output 报告 prefab 路径。

QA — QA Engineer:
  对照 PM 契约验收 UI prefab 完整性 + 图片 reference 解析 OK。
```

#### Audio Crew

```
Head — Audio Designer:
  把 task.output_paths（.wav 文件）转化为音效规格：
    - 每个文件对应的音效类型（jump / hit / pickup / ...）
    - 持续时间（毫秒）
    - 8-bit 风格关键词（如方波 / 短促 / 轻快）
  调 emit_output 提交 audio spec。

Executor 1 — Audio Synthesizer:
  对 task.output_paths 每个 .wav：调 synth_8bit_sfx(name, sfx_type, duration_ms, out_dir) 真合成。
  严禁 write_file 写空 wav 占位。
  调 emit_output(file_paths=...) 报告。

Executor 2 — Unity Developer:
  把每个 .wav 通过 manage_asset 配为 AudioClip（import setting 包括 stereo/mono / load type）。
  如 task.detail 要求，建一个 AudioManager.cs 关联这些 clip（可选）。
  调 emit_output 报告。

QA — QA Engineer:
  对照 PM 契约：.wav 存在 + size > 0 + RIFF/WAVE header 合法 + .meta 齐全。
```

#### Scene Assembly Crew

```
Head — Level Designer:
  扫上游所有已完成 task 的产物（read .mycrew/blueprint.json + list_directory_local Assets/），
  生成场景装配清单：
    - 要实例化的 prefab 列表 + 在场景中的位置
    - GameObject 命名 + 父子关系
    - 需要挂的脚本（哪个 GameObject 挂哪个上游 task 产的 .cs）
    - 关键引用（GameObject 之间的 reference 设置）
  调 emit_output 提交 assembly spec。

Executor — Unity Developer:
  按 spec 用 Unity MCP 装配场景：
    manage_scene load → manage_gameobject create（带 prefab_path）→ 
    manage_components add（挂脚本）→ set_property（配引用）→ manage_scene save
  目标场景路径默认 Assets/Scenes/Main.unity（可在 task.output_paths 指定其他）。
  调 emit_output 报告。

QA — QA Engineer:
  对照 PM 契约验收：
    1. 场景文件存在
    2. 用 manage_scene load 能成功加载（无 Missing reference 错误）
    3. spec 中列的每个 GameObject 在场景里能 find_gameobjects 到
  调 emit_output。
```

### 预设 Performer Pool（13 个 — 8 Crew + 5 单 Agent）

#### Crew（8 个，预设 seeded）

| Crew | applicable_scenarios | Head | Executor(s) | QA |
|---|---|---|---|---|
| **Art Crew** | 2D sprite / 概念图 / UI 图 / 任何 PNG 图像资源 | Art Director | Concept Artist → ComfyUI Image Generator → Technical Artist | QA Engineer |
| **3D Asset Crew** | 3D 模型（角色 / 道具 / 环境） | Art Director | 3D Modeler → Technical Artist | QA Engineer |
| **Animation Crew** | 角色 / 物体动画 | Art Director | 3D Modeler（rig）→ Animator → Technical Artist | QA Engineer |
| **VFX Crew** | 粒子特效 / 视觉效果 | Art Director | VFX Artist → Technical Artist | QA Engineer |
| **System Implementation Crew** | C# 玩法系统脚本（包括 PlayerController / EnemyAI / 战斗 / 关卡生成等） | System Designer | Unity Developer | QA Engineer |
| **UI Implementation Crew** | UI 界面（Canvas + Image + Text） | UI/UX Designer | ComfyUI Image Generator → Unity Developer | QA Engineer |
| **Audio Crew** | 音频（SFX / BGM） | Audio Designer | Audio Synthesizer（新 agent，调 synth_8bit_sfx）→ Unity Developer | QA Engineer |
| **Scene Assembly Crew** | Unity 场景装配（实例化 prefab + 挂脚本 + 配引用） | Level Designer | Unity Developer | QA Engineer |

#### 单 Agent（5 个，应对简单任务）

| Agent | 适用场景 |
|---|---|
| **项目初始化助手** | Phase 4 setup task（mkdir） |
| **Narrative Designer** | 纯文档输出（叙事 / 文案） |
| **Level Designer** | 关卡设计文档（如不带场景实装） — 注：与 Scene Assembly Crew 的 Head 同 role 同 agent，单一职责"出规格" |
| **System Designer** | 系统设计文档（不实装） — 注：与 System Implementation Crew Head 同理 |
| **Art Director** | 美术风格指南文档（不实际产资产） — 注：与多个 Crew Head 共享 |

→ **同一个 agent 既可被独立选中，也可作为 Crew 的一个 step**。它的"职责"是 "produce spec / 文档"，只做这一件事，不冲突。

#### 删除（5 类）

- Plan Maker（v2 PM 入口，废）
- Project Manager（PM v3 已替代）
- Project Structure Manager（PM v3 项管 phase 已干这事）
- 9 个 auto-gen Unity 工程师（删，让 Phase 5 复用 seeded Unity Developer）
- VFX Artist 标 deprecated 状态（合并到 VFX Crew 内部）— 暂保 row，停止单独被选

### Phase 2 也要看到 Crew 菜单

Phase 2（系统策划）是写任务列表的入口。如果它**不知道**有哪些 Crew 可选，会写出和 Crew 能力不匹配的任务（如把"出 sprite + 实装"硬拆成两个 task）。

→ Phase 2 backstory 加一段：

```
## 可用执行单元
- 单 Agent（适合单步任务）：项目初始化助手、Narrative Designer、Level Designer (出文档)、
  System Designer (出文档)、Art Director (出文档)
- Crew（适合产真东西，自带 QA）：
    Art Crew         - 2D sprite / 概念图 / UI 图（含 ComfyUI 真生图 + Unity 导入）
    3D Asset Crew    - 3D 模型（Blender 建模 + Unity 导入）
    Animation Crew   - 动画（Blender 关键帧 + Unity AnimatorController）
    VFX Crew         - 粒子特效（Blender 资产 + Unity Particle System）
    System Impl Crew - C# 脚本系统（设计规格 + Unity Developer 实现）
    UI Impl Crew     - UI 界面（设计 + 图 + Canvas 装配）
    Audio Crew       - 音频（8-bit 合成 + Unity AudioClip 导入）
    Scene Assembly Crew - Unity 场景装配（实例化 prefab + 挂脚本 + 配引用）

# 拆任务时按这些"能力单元"切。一个 task 对应一个 Crew/Agent 能完成的范围。
# 不要把一件事拆成多个 task（如不要"先出脚本"+"后挂脚本"分两 task，那是 System Impl Crew 一个 task 干的事）。
```

Phase 3 / 4 也加上类似（更精简）的提示，让审核 + 项管知道下游执行的颗粒度。

### Phase 5 改造

```python
# 旧 PM v3：assignments 里只能填 agent_id，且 assign_agents tool 还允许
#          通过 new_agent 字段创建新 agent（footgun）
# 新 PM v4：
#   - 工具叫 submit_assignments，每条 assignment 的 performer_ref = (agent 或 Crew)
#   - **完全删除** new_agent 创建路径（LLM 只能从预设池选）
#   - 候选池由 _render_performer_pool() 注入到 backstory，含 8 Crew + 5 单 agent
async def _render_performer_pool(session) -> str:
    agents = [single-purpose agents 5 个（不含 Crew 内部专用 agent）]
    crews = [Crew 8 个 + applicable_scenarios + 内部链]
    return formatted_menu

# Phase 5 prompt 关键约束：
#   "从下方 performer 池中给每个 task 选一个。两类：
#    - **agent**: 单一职责轻任务（如 mkdir、纯文档输出）
#    - **Crew**: 多 step 协作 + 自带 QA，适合产出真实可运行 artifact
#    每个 performer 标了 applicable_scenarios，按 task title + detail 匹配最近的。
#    **严禁创建新 performer**。**严禁返回不在池里的 id**。"
```

`SubmitAssignmentsArgs` schema：

```python
class PerformerRef(BaseModel):
    kind: Literal["agent", "crew"]
    id: str

class Assignment(BaseModel):
    task_index: int
    performer_ref: PerformerRef   # 新；替代旧 agent_id
    reason: str
    # **没有** new_agent 字段，从根本上拒绝创建动作
```

### workflow_svc 执行支持

```python
async def _run_agent(project_id, task_id, task_input):
    task = await crud.get_by_id("tasks", task_id)
    performer = task.get("performer_ref") or {"kind": "agent", "id": task.get("agent_id")}

    if performer["kind"] == "agent":
        return await self._run_single_agent(...)  # 现状
    else:
        return await self._run_crew(performer["id"], task_input)

async def _run_crew(crew_id, task_input):
    crew = await crud.get_by_id("crews", crew_id)
    sequence = json.loads(crew["agent_sequence"])
    # 构造 CrewAI Crew(Process.sequential, agents=[...], tasks=[...])
    # 每个 Task 的 description = step_instructions + (上一步 output)
    # step_callback 广播 task.sub_step WS 事件
    # 最后一步 (QA) 调 emit_output 提交聚合产物
```

### emit_output 校验漏洞修复

```python
# 1. 加 file_paths 字段名
_PATH_FIELD_NAMES = (
    "file_path", "filepath", "path",
    "file_paths",  # ← 加这个（复数）
    "image_path", "asset_path", "script_path",
    "output_path",
    "output_paths",  # ← 加这个（复数）
)

# 2. _gather_paths 看见 dict 的 key 是复数 path 字段时，value 应该是 list[str]
def _gather_paths(payload, out):
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in _PATH_FIELD_NAMES:
                if isinstance(v, str) and v.strip():
                    out.append(v.strip())
                elif isinstance(v, list):
                    # 复数字段：list of strings 直接展开
                    for item in v:
                        if isinstance(item, str) and item.strip():
                            out.append(item.strip())
            else:
                _gather_paths(v, out)
    elif isinstance(payload, list):
        for item in payload:
            _gather_paths(item, out)
```

### 工具集补齐

| Agent | 加挂的工具 |
|---|---|
| **Unity Developer** | 全部 34 个 Unity MCP（`manage_scene/gameobject/components/scripts/asset/material/texture/...`） |
| **Technical Artist** | Unity MCP 资产子集：`manage_asset / manage_material / manage_texture / manage_graphics / manage_packages` + Blender 子集（`import_generated_asset`） |
| **Animator** | 加 `import_generated_asset` |
| **Audio Synthesizer**（新建） | `synth_8bit_sfx`（builtin）+ `write_file` + `emit_output` |

### 新 builtin tool: synth_8bit_sfx

```python
class Synth8bitSfxArgs(BaseModel):
    name: str               # 文件名（不含扩展名）
    sfx_type: Literal["jump", "hit", "pickup", "explosion", "shoot", "footstep", "victory", "death"]
    duration_ms: int = 500
    out_dir: str           # 相对路径，如 "Assets/Audio/SFX/"

# 实现：用 numpy 合成方波 + 三角波 + ADSR 包络 + 噪声
# 保存为 16-bit PCM WAV 到 <project_root>/<out_dir>/<name>.wav
# 返回 file_path
```

### 画布可视化（前端）

**任务卡片尺寸 + 间距重算**：

卡片 200 → 240px 是 +20%。卡片内部高度大约 170 → 200px（同步放大）。间距按"和卡片同比例放大"原则：

| 维度 | 当前 | 调整后 | 算法 |
|---|---|---|---|
| TaskNode 宽 | 200px | 240px | +20% |
| TaskNode 高（自然） | ~170px | ~200px | 内容跟随宽度放大 |
| COL_W（横向 stride） | 340 | 380 | 240 + 140px 边距，140 是品质标线 |
| ROW_H（纵向 stride） | 250 | 290 | 200 + 90px 边距（之前 80 不够给 halo + 黄标） |

Crew 展开后宽度大致是 N 个子卡片 + 间隔 ≈ 子卡数 × 180 + 60 (header)。比如 5-step 的 Art Crew 展开 ≈ 5×180+60 = 960px。下游平移逻辑（B 方案）按这个宽度 delta 平移。

**新 `CanvasCrewNode` 组件**：

```tsx
function CanvasCrewNode({ data, selected }) {
  const [expanded, setExpanded] = useState(false);
  // 折叠态 → 复用 TaskNode 视觉 + 右下角 ⊕（展开按钮）
  // 展开态 → 外圈框架（与 TaskNode 同 halo/状态色）+ 横向 flex 子卡片串

  if (!expanded) return <TaskNodeWithExpand task={data.task} onExpand={...} />;

  return (
    <div className="crew-expanded-frame" /* halo/状态机 与 TaskNode 一致 */>
      <header>
        <span>{crew.name} · {task.title}</span>
        <button onClick={() => setExpanded(false)}>⊖</button>
      </header>
      <div className="flex flex-row gap-2">
        {crew.agent_sequence.map((step, i) => (
          <SubAgentCard
            step={step}
            stepIndex={i}
            status={subStepStatus[i]}
            // Head 子卡片：full action set，等同于普通 TaskNode 的编辑/暂停/重试
            // Executor + QA 子卡片：只读，仅对话 + IO 查看
            actions={step.role === "head"
              ? ["edit", "pause", "retry", "chat", "view_io"]
              : ["chat", "view_io"]}
            onAction={(action) => handleSubStepAction(task.id, i, action)}
          />
        ))}
      </div>
    </div>
  );
}
```

**Sub-card 动作 — 行为定义**：

| 动作 | 仅 Head | 行为 |
|---|---|---|
| `edit` | ✓ | 打开编辑器，编辑 Head 的 step_instructions（注：不允许动 task.output_paths / acceptance_notes — 那是 PM 的事） |
| `pause` | ✓ | task-level pause（影响整个 Crew） |
| `retry` | ✓ | 从 Head 起重跑（Executor + QA 跟随重跑；上游 task 不动） |
| `chat` | 所有 | 进 task_guidance，scope 到该 step 的 in.md / out.md |
| `view_io` | 所有 | 打开 IO viewer，看该 step 的输入输出 |

**下游平移逻辑**（CanvasBlueprint 内部）：

```tsx
const [expandedCrewWidths, setExpandedCrewWidths] = useState<Map<crewTaskId, deltaPx>>(new Map());

// 渲染节点位置时
const renderedX = node.position_x + sumDeltasToTheLeftOf(node, expandedCrewWidths);
```

不持久化、不改 DB。收起即复位。

**子卡片的「对话」「IO 查看」**：

- 「对话」：调 `POST /workflow/tasks/{task_id}/guidance` + 新增 `?step_index=N&agent_id=...` query param。后端在 task_guidance 加上下文 = "你只看 step N 的 in.md / out.md，不要回答整任务问题"
- 「IO 查看」：新 endpoint `GET /workflow/tasks/{task_id}/sub_io?step_index=N`，返回该步骤的 in.md / out.md
- 每个 Crew step 落 IO 到 `<OUTPUT_DIR>/<pid>/<tid>/sub/<step_index>_<role>_<in|out>.{json,md}`

### WS 事件 `task.sub_step`

```python
manager.broadcast("task.sub_step", {
    "task_id": task_id,
    "step_index": int,
    "role": "head" | "executor" | "qa",
    "agent_id": str,
    "status": "started" | "completed" | "failed",
    "ts": iso,
})
```

前端 `CanvasCrewNode` 监听并更新 `subStepStatus`。

---

## 关键文件改动

### 后端

| 文件 | 改动 |
|---|---|
| `backend/migrations/versions/0013_crew_pool.py` | 新 — crews 加 applicable_scenarios + agent_sequence；任务表加 performer_ref TEXT |
| `backend/bootstrap/seed_crews.py` | 新 — seed 8 个 Crew |
| `backend/bootstrap/seed_planner_agents.py` | 扩 — 加 Audio Synthesizer；删 PM/PSM/PMgr 类 agent |
| `backend/bootstrap/seed_builtin_tools.py` | 加 `synth_8bit_sfx` |
| `backend/src/tools/builtin/local/synth_8bit_sfx.py` | 新 |
| `backend/src/tools/builtin/local/emit_output.py` | _PATH_FIELD_NAMES 加复数 + _gather_paths 支持 list |
| `backend/services/workflow_svc.py` | 加 `_run_crew()` + crew io 落盘 |
| `backend/services/crewai_runner.py` | 加 `run_crew_with_crewai()` (Process.sequential) |
| `backend/agents/sub_agents/_planner_models.py` | `Assignment.performer_ref` |
| `backend/agents/sub_agents/_planner_orchestrator.py` | Phase 5 prompt + assemble crew assignments |
| `backend/agents/sub_agents/_planner_prompts.py` | Phase 5 backstory（按 performer pool 选） |
| `backend/api/routes_workflow.py` | 加 `GET /tasks/{id}/sub_io` + extend `guidance` 接受 step_index |
| `backend/agents/task_guidance.py` | 支持 step 级别上下文 |
| 数据迁移脚本 | 一次性：把现有 task.agent_id 转 task.performer_ref={kind:agent,id:...}；删 9 个 auto-gen agents；删 Plan Maker / PM / PSM |

### 前端

| 文件 | 改动 |
|---|---|
| `frontend/src/components/task/TaskNode.tsx` | 尺寸 +20%（200→240） |
| `frontend/src/components/task/CanvasBlueprint.tsx` | ROW_H 250→280，COL_W 340→380；nodeTypes 加 "crew" |
| `frontend/src/components/task/CanvasCrewNode.tsx` | 新组件 |
| `frontend/src/components/task/SubAgentCard.tsx` | 新组件（迷你 TaskNode 风格） |
| `frontend/src/queries/useProjectQuery.ts` | Task 类型加 performer_ref |
| `frontend/src/components/task/AgentChatDrawer.tsx` | 支持 step_index（路由进来时带） |

---

## 复用现有

| 复用项 | 来源 |
|---|---|
| CrewAI 的 Process.sequential | `crewai_runner._build_crewai_llm` + Crew(process=Process.sequential) |
| TaskNode 视觉 | `TaskNode.tsx` 整套（folded crew 复用、sub card 复用） |
| io_in_ref / io_out_ref / blueprint_writer | 已有，扩展到 sub-step 级 |
| emit_output 整体框架 | 仅修复 _gather_paths 漏洞 |
| seed pattern | 复用 seed_planner_agents.ensure_xxx 的 idempotent 模式 |
| _llm_picker 三档 | 不变 |
| pm.log / pm_state | 不变；只新增 task.sub_step |

---

## 实施分阶段

| 阶段 | 内容 | 验证 |
|---|---|---|
| **A** | emit_output 漏洞修复 + builtin synth_8bit_sfx 工具 + seed 一个测试 wav | unit test：emit_output 拒绝 file_paths 里 path 不存在的 case |
| **B** | migration 0013 + 删除 9+3 个 agent + seed 8 个 Crew（agent_sequence JSON）+ seed Audio Synthesizer agent | DB 行数对得上；启动日志无 error |
| **C** | workflow_svc._run_crew + crewai_runner.run_crew_with_crewai + sub-step io 落盘 + task.sub_step WS event | mock 一个 1-step Crew 跑通；逐步加到 2/3-step |
| **D** | Phase 5 改造（performer_ref + prompt + assignment）+ PM v3 orchestrator assemble 改造 | mock 一个 PM v4 跑通跑出含 crew 引用的草稿 |
| **E** | 工具集补齐（Unity Developer / Technical Artist 加 MCP 工具）+ migration 重新分发 tool_ids | 启动日志各 agent 工具数对得上 |
| **F** | 前端：TaskNode 尺寸 + CanvasCrewNode + SubAgentCard + 下游平移 + WS 监听 | 真跑一个 Art Crew 任务看子卡片实时高亮 |
| **G** | 前端：子卡片的「对话」「IO 查看」按钮 + 后端 sub_io endpoint + guidance step_index 扩展 | 手测 |
| **H** | 端到端真实 LLM 跑一个 Unity 项目，验证 Art Crew / Scene Assembly Crew / System Implementation Crew 都能产真东西 | 看 Pac-Man 那个 Assets/Sprites/ 这次有真 PNG 落盘 |

---

## 验证

### 自动化（smoke）
- emit_output 修复：mock payload `{file_paths: ["fake/nonexistent.png"]}` → 必须 reject
- workflow_svc._run_crew：mock 3-agent Crew，验证 step_callback 触发 3 次、io 落盘 3 套、最终 emit_output 拿到 QA 的提交

### 手测（端到端）
1. 新建 Unity 项目 → PM v4 跑 → Phase 5 选 performer → 草稿里出现 `performer_ref: {kind:"crew", id:"crew_art"}`
2. 保存项目 → 启动 → Crew 任务执行 → 看 sub_step WS 事件流 → 子卡片高亮按 head→executor→QA 顺序流转
3. 完成后 `F:/UnityProjects/<pro>/Assets/Sprites/` 里有**真实 PNG 文件**（emit_output 不再被 file_paths 漏校验糊弄）
4. 展开 Crew 卡片 → 下游节点自动右移 → 收起复位
5. 子卡片点「对话」 → 进 guidance 聊天，上下文限定到该 step
6. 子卡片点「IO 查看」 → 看该 step 的 in.md / out.md

---

## 风险 + 缓解

| 风险 | 缓解 |
|---|---|
| Crew 串接 LLM token 大幅上涨 | head + QA 都用 cheap LLM（deepseek-flash）；executor 才上 pro |
| CrewAI Process.sequential 在 step 间传 output 格式不可控 | 用 `step_instructions` 显式约束每一步格式 + Pydantic 校验中间产物 |
| 8-bit 音频质量低 | 接受（用户已确认）；保留未来切到 AudioCraft 的接口 |
| performer_ref schema 改动 影响现有项目 | migration 把所有现有 task.agent_id 转为 `performer_ref:{kind:"agent",id:...}`；前端兼容渲染 |
| 删 auto-gen 工程师后历史项目里指向它们的 task 失效 | migration 同时把这些 task 的 performer_ref 重定向到 seeded Unity Developer |
| 9 个 auto-gen agent 的 tool_ids 短小 | 删了就好，复用 seeded Unity Developer（工具齐） |

---

## 不在本轮

- AudioCraft / 真音乐生成（用户决定后期再做）
- Crew 内的条件分支 / 跳步（MVP 只支持线性串行）
- iterate_existing 流程的 Crew 化（用户先前已决定 v3 留待后续，v4 延续这个决定）
- 修复 PM v4 vs PM v3 老草稿的并存兼容（直接覆盖，不维护多版本）
