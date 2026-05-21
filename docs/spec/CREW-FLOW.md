# Crew 工作流 — 端到端流程与分工

**目的**：把 MyCrew 从「用户提需求」到「产物落盘」的完整链路画出来，标清楚每个节点用 LLM 还是脚本，**为什么**。

> 架构核心原则
> **创作给 LLM，验证给脚本，可枚举决策给脚本，主观判断给 LLM。**

---

## 1. 高层骨架

```
用户提需求 (自然语言)
  │
  ↓
┌─────────────────────────────────────────────────────────┐
│ Inception (LLM) — 跟用户聊清楚要做什么                  │
└─────────────────────────────────────────────────────────┘
  │ project draft
  ↓
┌─────────────────────────────────────────────────────────┐
│ PM 工作流 (6 phases)                                    │
└─────────────────────────────────────────────────────────┘
  │ tasks[] with output_paths + output_schema + code_contract
  ↓
┌─────────────────────────────────────────────────────────┐
│ Crew 执行（每个 task 一次 Crew）                        │
└─────────────────────────────────────────────────────────┘
  │ files on disk + verdict
  ↓
最终交付
```

---

## 2. PM 6 个 Phase

```
Phase 1: Concept            [LLM]    用户需求 → 一段 ConceptDoc
                              │
Phase 2: Atomic Tasks       [LLM]    Concept → tasks 数组(粗)
                              │
Phase 3: Review             [LLM]    每个 task 补 acceptance_notes
                              │
Phase 4: Project Mgmt       [LLM]    每个 task 给 output_paths + setup
                              │
Phase 5: Code Contract      [LLM]    .cs task 给 namespace + signatures
                              │
Phase 6: Assignment      ★ [脚本] ★ output_paths suffix → Crew 映射
                              │
                              ↓
                     tasks 已分派到具体 Crew
```

**Phase 6 为什么脚本化**：`output_paths` 后缀到 Crew 的映射是确定的（.png → 2D 美术，.cs → 系统实现，等等），不需要语义推理。

---

## 3. 单个 Crew 内部（以 2D 美术资产组为例）

```
task (含 prompts spec 契约) 进入 Crew
  │
  ↓
┌──────────────────────────────────────────────────────┐
│ Step 0: Art Director           [LLM]                 │
│ ─────────────────────────                            │
│ 输入: task.detail + output_paths + output_schema     │
│ 输出 (emit_output):                                  │
│   { width, height, style, palette,                   │
│     model: { checkpoint, steps, cfg, sampler, ...},  │
│     prompts: { <path>: {pos, neg, seed}, ... } }     │
│ 失败处理: _rescue_react_emit_output 救;救不到 halt   │
└──────────────────────────────────────────────────────┘
  │ head_spec
  ↓
┌──────────────────────────────────────────────────────┐
│ Step 1: ComfyUI Generator    ★ [脚本] ★ (fan-out)   │
│ ─────────────────────────                            │
│ 每个 child 一次：                                    │
│   1. _resolve_checkpoint(head_spec.model.checkpoint) │
│   2. _choose_gen_size(契约 w×h → SD 区间钳制)        │
│   3. _build_txt2img_workflow(prompts, params)        │
│   4. POST http://127.0.0.1:8000/prompt → prompt_id   │
│   5. poll /history/<id> 到 done                      │
│   6. GET /view?filename=... 拿 PNG 字节              │
│   7. PIL resize → 契约尺寸                           │
│   8. 落盘 root_path/<output_path>                    │
│ 输出: {verdict, file_paths, width, height, issues}   │
└──────────────────────────────────────────────────────┘
  │ {file_paths: [Butcher_64.png, Butcher_512.png, ...]}
  ↓
┌──────────────────────────────────────────────────────┐
│ Step 2: Technical Artist     ★ [脚本] ★             │
│ ─────────────────────────                            │
│ 每个产物文件：                                       │
│   1. suffix dispatch (.png/.jpg → texture, etc.)     │
│   2. decide_texture_import(path, detail, w, h, alpha)│
│      → {textureType, filterMode, wrapMode,           │
│         spriteMode, ppu, mipmap, maxSize, ...}       │
│   3. 调 Unity MCP manage_asset action=modify         │
│      properties=<上面那个 dict>                      │
│   4. 调 refresh_unity 触发 AssetDatabase.Refresh     │
│ 输出: {verdict, imported: [{path, settings}, ...]}   │
│ 非 Unity 项目 (无 ProjectSettings/) 自动 skip + pass │
└──────────────────────────────────────────────────────┘
  │ {imported: [...]}
  ↓
┌──────────────────────────────────────────────────────┐
│ Step 3: QA                    ★ [脚本] ★            │
│ ─────────────────────────                            │
│ 对每个 output_path：                                 │
│   1. 文件存在 + size > 0                             │
│   2. PIL 打开成功（隐式 magic check）                │
│   3. 实际尺寸 == 契约尺寸                            │
│   4. 透明度检查（如果 detail 要求）                  │
│   5. 上游 Executor verdict 透传                      │
│ 输出: {verdict: pass/fail, issues: [...]}            │
└──────────────────────────────────────────────────────┘
  │
  ↓
task done / validation_failed
```

---

## 4. 8 个 Crew 整体分工矩阵

| Crew 类型 | Head | Executor | TA | QA |
|---|---|---|---|---|
| 2D 美术 | LLM | **脚本** | **脚本** | **脚本** |
| 3D 模型 | LLM | LLM (Blender) | **脚本** | **脚本** |
| 动画 | LLM | LLM (Blender) | **脚本** | **脚本** |
| 特效 | LLM | LLM (Blender) | **脚本** | **脚本** |
| 系统实现 | LLM (架构师) | LLM (Unity Dev 写代码) | — (.cs 无 importer) | **脚本** + 契约 AST |
| UI 实现 | LLM | LLM (Unity Dev) | **脚本** (.png) | **脚本** |
| 音频 | LLM | LLM (8-bit 合成；可脚本) | **脚本** | **脚本** |
| 场景装配 | LLM | LLM (Unity Dev 装配) | — (.unity 无 importer) | **脚本** |

**LLM 留在的位置统一就两类**：
- **Head / Director**：定艺术方向、写 prompt、写代码契约
- **Executor**：真在调 Blender / Unity 这类复杂状态机工具产内容（图像生成已脚本化；3D/动画/音频/Unity 代码仍是 LLM，复杂度高）

---

## 5. 端到端时序图（理想态，TA 脚本化后）

```
T+0.0s   PM Phase 1-5 (LLM)                ~60s
T+60s    PM Phase 6 (script)               <1ms
T+60s    task 调度
T+61s    Crew 启动 - Art Director (LLM)    ~20s
T+81s    ComfyUI Generator (script×3 par)  ~30s (GPU 串行 = concurrency_cap 1)
T+111s   Technical Artist (script×3)       ~5s (Unity MCP 3 次 modify)
T+116s   QA (script)                       <1s
T+117s   contract check / final QA
T+118s   task done

3 张图，约 2 分钟。当前 LLM TA 同样链路约 5 分钟（TA agent 来回试工具 + 多次 emit 失败）。
```

---

## 6. 失败 / 兜底路径

```
任何 LLM 步骤 captured=None
  ├─► _rescue_react_emit_output(raw_text) 抽 JSON
  │     ├─ 救到 → 继续往下走
  │     └─ 救不到 → halt 整 Crew (RuntimeError 带诊断)
  │
任何脚本步骤抛 ComfyHttpError / UnityMcpError
  ├─► 直接 verdict='fail' 返回
  └─► fan-out 子任务 status=failed

QA 报 fail (无论 LLM 还是脚本)
  └─► failure_analyzer (LLM) 把错误日志解读成人话
      写到 task.failure_analysis

contract check (script, post-Crew)
  ├─ 缺少签名 但可补 → contract Debugger (LLM) 跑一次补丁
  └─ 全部满足 → task done
```

---

## 7. 「脑 / 手」分工

```
          创作 / 综合 / 改写 / 写代码
       ┌────────────────────────────────┐
       │             LLM                │
       │  Head / Director / Executor    │
       │  (创造性工具)                  │
       └──────────┬─────────────────────┘
                  │ 输出"做什么"的规格
                  ▼
       ┌────────────────────────────────┐
       │           脚本                 │
       │  Phase 6 路由 / Generator 出图 │
       │  TA 配 importer / QA 验真假    │
       │  (机械执行 + 验证工具)         │
       └────────────────────────────────┘
```

---

## 8. 当前规模与演进

| 阶段 | 改造 | 落地时间 | 收益 |
|---|---|---|---|
| Stage 0 | 全 LLM 链路 | 项目早期 | 灵活但失败率高 |
| — | Phase 6 → 脚本路由 | 2026-05-19 | <5ms / 0 token；路由零幻觉 |
| — | 代码契约 AST 验证 → 脚本 | 2026-05-18 | tree-sitter 替代 regex |
| Stage 2 | QA → 脚本 | 2026-05-20 | 所有 8 个 Crew 的 QA 不再调 LLM；文件不存在终于会被报出来 |
| Stage 3 | ComfyUI Generator → 脚本 | 2026-05-20 | 真出图（HTTP API 直连，绕开 LLM 工具调用失败模式） |
| **Stage 4** | **TA → 脚本** | **2026-05-20** | **统一 importer 设置；同项目不再每张图配不同 filter** |
| 未来 | 8-bit 音频合成 → 脚本 | — | DSP 是机械操作 |
| 未来 | Unity Developer 部分脚本化 | — | 简单 CRUD 类代码生成可模板化 |

**LLM 调用密度**：从 Stage 0 的 ~32 个 LLM step (4×8 crews)，到 Stage 4 的 **10-12 个 LLM step + 20-22 个脚本 step**。LLM 调用密度降低 ~65%，链路稳定性显著提高。

---

## 9. 何时该脚本化、何时该保留 LLM

判断准则：**这件事如果叫 5 个不同的有经验的人做，他们会做同样的事吗？**

- **会** → 脚本（决策可枚举、判定客观）
- **不会** → LLM（需要创作 / 语义 / 主观判断）

具体应用在 MyCrew 上：

| 决策 | 5 人是否一致 | 工具 |
|---|---|---|
| `Foo.cs` 路由到哪个 Crew | 一致（看后缀） | 脚本 |
| Butcher 头像的 positive prompt 怎么写 | 不一致（艺术判断） | LLM |
| `.png` 文件存在吗 | 一致（fs.exists） | 脚本 |
| 这段代码逻辑是否合理 | 不一致 | LLM（或留给真人 PR review） |
| 像素艺术 Texture 应该用 Point filter | 一致 | 脚本 |
| 这张图风格是不是真的像黑袍纠察队 | 不一致（需要视觉模型 + 主观） | 当前无解（vision LLM 或人工） |

---

## 10. 反模式

**LLM 不该做的事**：
- 数学（除非用 code-interpreter）
- 严格 schema 输出（function calling 也不 100% 可靠 — 我们已经被坑过）
- 同样输入要求同样输出
- 高频次同质操作（贵 + 慢）
- 安全 / 权限判定

**脚本不该做的事**：
- 翻译 / 改写自然语言
- 主观打分 / 品味判断
- 全新场景的兜底（脚本只会按规则走，没规则就 fail）
- 长尾边界（"用户输入了一句我们没想到的话"）

警惕「**全脚本化主义**」——一旦要语义理解 / 泛化 / 写自然语言，脚本会写得越来越复杂还盖不住边界，最后用一堆烂规则模拟出一个差版本的 LLM。该回去用 LLM 就回去用。

---

## 引用

- 关键代码：
  - [services/qa_script.py](../../backend/services/qa_script.py) — Stage 2 脚本 QA
  - [services/image_gen_script.py](../../backend/services/image_gen_script.py) — Stage 3 ComfyUI 直连
  - [services/asset_import_script.py](../../backend/services/asset_import_script.py) — Stage 4 TA 脚本（本期）
  - [services/workflow_svc.py](../../backend/services/workflow_svc.py) `_run_crew` / `_fanout_step` — kind 分支调度
  - [bootstrap/seed_crews.py](../../backend/bootstrap/seed_crews.py) — Crew sequence 定义
  - [agents/sub_agents/_planner_orchestrator.py](../../backend/agents/sub_agents/_planner_orchestrator.py) `_assign_performers_by_rule` — Phase 6 路由规则
- 相关 ADR / 设计讨论：见 `docs/ADR/`
