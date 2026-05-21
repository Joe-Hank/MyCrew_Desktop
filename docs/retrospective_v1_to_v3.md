# 从 v1 到 v3：一个 CrewAI 多智能体 Unity 自动开发项目的三轮迭代复盘

> 这是一篇技术讨论文章，不是产品宣传。我把 MyCrew 项目从 v1（一个 CrewAI 模板 demo）到 v2（弃用的桌面应用）再到 v3（当前 188 commits、约 6 万行代码的 Tauri + FastAPI 工程）的全部弯路、踩坑、反思摆开来谈，希望能对正在用 CrewAI / LangGraph 做"AI 全链路代码生成"的同行有参考价值。

---

## 一、项目目标与最终面对的现实

**项目立项的口号**：用 CrewAI 多智能体编排 + Unity MCP，让 AI 从一句话需求自动产出可玩的 Unity 游戏。

**两个月后能给出的真话**：

- **能做到**：单个 C# 脚本生成、确定性的资源处理（图片/音频脚本化）、半自主的多步骤流水线 + 人审 checkpoint
- **做不到**：按一个按钮、不干预、产出一个 Unity 可玩项目
- **关键事实**：在最近一次 N=5 × 5 LLM provider 组合的实测里，CrewAI 的核心交接工具 `emit_output` **0/25 次被 agent 自然触发**——所有"成功"的运行都依赖 4 层 rescue 兜底

这不是悲观，是 2026 年这个时间点用现有大模型 + CrewAI 生态做这类工程**真实的能力边界**。文章后半段会把这个数据展开。

---

## 二、v1 → v2 → v3 的三段路

### v1（Claude-CrewAIWorkflow，2026-04-22 起步）

**形态**：一个 Python CLI，纯 CrewAI 模板，演示"research → summarize"两步流。8 个 commits，目录里没有 UI，没有数据库，只有一份 `pyproject.toml` 和几个 agent yaml。

**目的**：验证 CrewAI 框架本身能不能跑、agent + tools + sequential process 的范式直觉是否成立。

**结论**：能跑。基础 demo 在 OpenAI / Anthropic 上都通。**但**：仅是验证。任何真实业务场景都不够。

### v2（MyCrew_v2，2026-04 末到 5 月初）

**形态**：在 v1 基础上加桌面壳（Tauri）+ 数据层 + YAML 驱动配置。Description.md 自评"生产就绪 (0.2.0)"，14 个专业 Agent、6 个 Crew、2 种 Flow（simple/complex）、8 个 MCP 集成。

**为什么弃用**（v3 的 Description.md 直白写明）：
> "v2 已实现完整桌面应用但因整体用户体验不佳、核心功能不稳定被弃用。v3 在空目录从零重构，参考 v2 的 IMPLEMENTATION_GUIDE.md 但不复用 v2 代码。"

**真正的 v2 失败点**（事后总结）：

1. **YAML 驱动配置**听上去"灵活"，实际上每次改 agent 都要手工编辑配置文件、重启、测试。**重新加载循环 > 30 秒**，导致迭代极慢。
2. **没有 PM（Project Manager）这一层**，用户输入直接喂给 Crew，意味着任务拆解的责任丢给 user 自己。
3. **CrewAI dynamic MCP integration 参数报错频发**——v2 用 `crewai-tools` 自带的 MCP wrapper，命中各种 schema 兼容性问题。
4. **没有 task 输出契约**，agent 自由发挥的产物没法被下游可靠消费。

**v2 的核心教训**：堆功能不解决稳定性问题。先有"能正确做完一件事"的基底再做 UI，不要倒过来。

### v3（MyCrew_v3，2026-05-09 起步至今）

**重写决定**：v3 在空目录从零起步。Tauri 2.x + React 19 (frontend) + Python FastAPI sidecar (backend) + SQLite 持久化。截至本文撰写时 188 个 commit、47 个 backend service 文件、约 6 万行代码。

下面把 v3 自身的几个大版本展开。

---

## 三、v3 内部的 PM v1 → v5 五次迭代

v3 的核心是 **PM（Project Manager）层**——把用户的自然语言需求拆解成可执行的 Task DAG。这一层经历了 5 次大改写，每次都有明确的"换思路"理由。

### PM v1（隐含，Phase 17 之前）

inception_svc 直接用 raw-LLM JSON-block prompting 让模型输出任务列表。**失败模式**：模型经常输出"形似 JSON 但有微小错误"的文本，validation_failed 率很高。

### PM v2（Phase 17，commit `2be5363`，5-13）

引入 CrewAI Plan Maker agent + `create_workflow` 工具。这是第一次用"agent + tool"替代"raw prompt + parse"。

**改进**：通过 tool 的 `args_schema` 让模型必须按结构出参数。
**遗留问题**：Plan Maker 是单个庞大 agent，1800-token backstory，处理 5 种意图，每轮 5 个 LLM iter。Token 消耗极重，慢。

### PM v3（commit `fffe1c8` 系列，5-15）

**渐进富集（progressive enrichment）的 Pydantic 链**：

```
ConceptDoc           ← Phase 1 主策划
AtomicTask           ← Phase 2 系统策划
ReviewedTask         ← Phase 3 审核策划（加 acceptance + schema）
PathedTask           ← Phase 4 项管（加 file_paths）
Assignment           ← Phase 5 指挥员
```

每个 phase 一个 LLM 调用 + 一个对应的 `submit_*` 工具验证 Pydantic 模型。**思想**：从一句话需求到完整任务规格，分 5 步走，每步只关心一件事；下游 phase 继承上游模型，schema 严格扩展不破。

**为什么这个范式有效**：commit message 直说——"v2 emit_output(payload: dict) 的范式 schema 在散文里，v3 LLMs 看到的是 function-calling signature 里的 strict args_schema，一次过率上去了"。

### PM v4（commit `393bf59` 系列，5-16）

**核心是 Crew 池架构**：

- 14 个单一职责 agent（Art Director / System Designer / QA Engineer 等）
- 8 个 Crew（System Implementation / UI Implementation / Audio / VFX / Scene Assembly / 等），每个 Crew 是 head→executor→QA 三步骤序列
- Tasks 表加 `performer_kind` + `performer_id`：一个 task 可以分配给单 agent 或整个 Crew

**为什么需要 Crew 池**：v3 早期一个 agent 干所有事，prompt 极长 + max_iter 不够 + 工具集过大 → agent 经常"想多步但只走一步就停"。Crew 把工作切碎到不同角色，每个角色拿到的 prompt + 工具集都聚焦。

**Plan Maker v2（同期 commit `75b3c44`）的 Dify 风格意图路由**：

> 把单 Plan Maker 替换成"前置过滤 → 合规闸 → 意图分类器 → 5 子 agent 分派"。Token 经济性从 25k/轮降到 1k-6k（视意图）。

### PM v5（commit `e3d0d84` / `c2c6d8a`，5-17）

**Code Contract**：PM Phase 5 designer 给每个代码任务输出一份"必须实现的公共符号清单"。Executor 写 .cs 时被注入这份契约，QA 走 regex 校验（**第一版**）。

**两天后**（commit `35cdd67`，5-18）regex 校验被升级为 **tree-sitter AST 语义匹配**。为什么？因为 regex 对 property body 风格过敏：契约写 `public int Score { get; set; }`，模型写 `{ get => _x; set { OnX?.Invoke(); } }`——同一个 API 不同 body，regex 假阴性。AST 走 `(kind, name)` 语义键匹配，body 风格无关，true positive 率显著上升。

**再一天**（commit `243ceff`，5-19）加 **Debugger 通道**：契约缺签名时，不直接 validation_failed，而是启 Debugger agent 跑一次精准补丁，只补缺的签名，不动业务逻辑。这是用"针对性修复"代替"整 task 重跑"，节约 token。

### 当前（5-21，本会话）

发生了一次架构级试错（详见第五节）：尝试用 `Task(output_pydantic=Spec)` 让 CrewAI 框架接管 schema 强制——实测推翻。回退原方案。

---

## 四、累积下来的"防御层"

到 5-21 为止，v3 在 Crew 执行链路上累积了**至少 7 个防御机制**，每个都是某次事故后加上去的：

| # | 防御层 | 来源事故 | commit |
|---|---|---|---|
| 1 | emit_output schema 校验 | v2 散文 schema 不可靠 | PM v3 |
| 2 | emit_output 路径存在性检查 | "agent 说写了但其实没写"漏洞 | 心之回廊 audit（5-13） |
| 3 | code_contract regex 校验 | Sonnet 漏 4-5 个签名 | PM v5（5-17） |
| 4 | code_contract AST 语义校验 | regex 假阴性 | 5-18 |
| 5 | `_rescue_react_emit_output` | agent 把 Action/JSON 写在 text 没调 emit_output | 5-20 |
| 6 | `_rescue_by_file_existence` | agent 用 create_script 写了文件但忘 emit_output | 5-20 |
| 7 | workflow_svc server-side disk truth check | agent 编 file_paths 但磁盘没文件（本会话发现） | 5-21 |

**这个清单本身是一个信号**：底层 framework 不给"硬保证"，所以每个失败模式都要在外面再补一道墙。

---

## 五、本会话的关键试错（output_pydantic 翻车）

值得单独讲，因为是最近也是最戏剧化的一次。

**假设**：CrewAI 1.14 的 `Task(output_pydantic=Spec)` 让框架接管 schema → 干净取代 emit_output 工具调用。

**Probe 1（孤立环境）**：用 Qwen-plus + ExecutorSpec 跑 N=10，**10/10 pydantic OK，9/10 一次成功，平均 1.1 LLM call/trial**。看起来非常好。

**Probe 2**：`tool_choice={"type":"function","function":{"name":"verify_outputs"}}` 在 Qwen 5/5 强制成功。架构看起来全绿。

**部署到生产（fruit-ninja 项目）**：
- 7 个代码 task：4 个 status=done **但磁盘上文件不存在**，3 个被新 server-side check 抓到失败
- **真成功：0**

**Phase 4 受控变量实验**：

| Variant | real_success |
|---|---|
| baseline (output_pydantic + 普通 prompt) | 0/5 |
| strong_prompt | 0/5 |
| high_iter (max_iter=8) | 0/5 |
| simple_tool | 0/5 |
| **no_pydantic (无 output_pydantic + verify_outputs)** | **5/5** |

**根因**：`Task(output_pydantic=Spec)` 让 Qwen agent 把目标从"做事再产 JSON"扭曲成"直接产 JSON"，工具循环被框架短路。**prompt 强化、提高 iter、换工具都无效**——只有不用 output_pydantic 才能恢复 agent 的工具调用行为。这是 CrewAI 1.14 一个未文档化的架构特性，社区 GitHub issue 里有类似抱怨（[#1338](https://github.com/crewAIInc/crewAI/issues/1338)、[#2895](https://github.com/crewAIInc/crewAI/issues/2895)）。

**反思**：Probe 1 测的是"能不能产出合法 Spec"，**没测"是否同时做了工具工作"**——两个本应正交的指标实际是负相关。**孤立单元测试的盲区**。后续任何涉及 output_pydantic 类设计，probe 必须同时观察"预期工具是否被触发"。

---

## 六、方法 / 结果总表

把这两个月试过的关键方法摊开：

| 方法 | 状态 | 结果数据 | 备注 |
|---|---|---|---|
| YAML 驱动 agent 配置（v2） | ❌ 弃用 | UX 反馈"难用" | 改 SQLite + 后端 API |
| 单庞大 Plan Maker agent（v3 早期） | ❌ 弃用 | 25k tokens/轮 | 改 Dify 风格意图路由 |
| 意图路由 + 5 子 agent（PM v2） | ✅ 沿用 | 1k-6k tokens/轮，按意图 | -75% to -96% |
| Pydantic progressive enrichment（PM v3） | ✅ 沿用 | schema 失败大幅下降 | 仍是主架构 |
| Crew 池 + performer_id（PM v4） | ✅ 沿用 | agent 职责单一化 | 仍是主架构 |
| code_contract regex 校验（PM v5） | ❌ 替换 | property body 风格假阴性 | 改 AST |
| code_contract tree-sitter AST | ✅ 沿用 | 21 test case 全过 | 真根因解 |
| Stage D Debugger 补丁 | ✅ 沿用 | 缺签名时只补不重跑 | 节约 token |
| CrewAI native deepseek path | ❌ 已知坏 | DSML token 5/5 泄漏 | 强制 is_litellm=True |
| LiteLLM 路径 + emit_output | ⚠️ 不可靠 | emit_output 0/5 自调 | 需 rescue 兜底 |
| `_rescue_react_emit_output` 等 4 个 rescue 分支 | ✅ 沿用 | 补救率提升 | 治标 |
| **Task(output_pydantic=Spec)（本会话试）** | **❌ 推翻** | **生产 0/7 真成功** | agent 跳工具 |
| verify_outputs 工具 + tool_choice specific | ✅ 沿用 | Qwen 5/5 强制成功 | 但 prompt 模式下 0/5 自调 |
| **workflow_svc server-side disk truth check** | ✅ 沿用 | **抓 100% agent 作弊** | 最后一道防线 |
| Qwen / GLM 替代 DeepSeek（structural 步骤） | ✅ 沿用 | Qwen response_format json_schema 支持 | DeepSeek reasoner 不支持 |

---

## 七、走过的弯路 / 误判的根因

**弯路 1：v1→v2 把 UI 做在不稳定核心之上**

v2 是"产品化优先"思路的典型失败——还没解决"AI 能不能可靠完成一件事"，就着急做 UI 让用户操作"它"。结果是用户看见一个看起来完整的 app，但每次跑都失败。**正确顺序**：先磨稳核心 1-2 个场景的端到端，再做 UI。

**弯路 2：迷信"agent 会按 prompt 守规矩"**

v3 早期 emit_output 的整个设计假设 agent 会主动调它。实测 0/5 真触发——agent 把 payload 写在 final answer text 里。每次失败就加一个 rescue 分支。**4 个 rescue 累积下来反思**：这不是 4 个独立 bug，是同一个架构假设（"工具会被调"）的 4 次破绽。应该早早承认这个假设站不住，把校验前置到 server-side。

**弯路 3：把 schema 严谨等同于"framework 接管"**

`Task(output_pydantic=Spec)` 看起来比 "agent 必须主动调 emit_output" 优雅——让框架做约束。Probe 1 数据漂亮（10/10）就贸然推进。**没意识到**：框架接管 schema 的代价是 agent 跳过 tool 循环。**教训**：评估架构改动时，**必须同时测"理想路径"和"副作用路径"**——10/10 schema 成功 + 0/5 工具调用 = 净负回归。

**弯路 4：code_contract 第一版选 regex**

写 regex 校验比写 AST 容易，但 regex 对代码风格过敏。这种"先用脆的、坏了再换"的选择，加上中间还把它当真理跑了几天的项目，**事后看：直接上 AST 是对的**。

**弯路 5：用 git log 做诊断、不用日志/产物**

会话中段我有一次"基于 commit history 模式匹配 → 给方案"——被用户直接打断："不要用 commit history 脑补根因"。教训：**诊断永远是 evidence-first**——读 `out.json`、读 LLM raw response、加 instrumentation，不是读 commit 揣测。

---

## 八、行业横向对比（2026-05 时点）

**CrewAI 自身现状**（来自 [DigitalbyDefault.ai 2026 report](https://digitalbydefault.ai/blog/crewai-multi-agent-orchestration-2026)）：
- 47.8K GitHub stars，2B agent runs，150+ enterprise customers
- 1.9.x 版本加了 CheckpointConfig 的状态持久化
- 与 LangGraph 对比代码生成成功率：CrewAI 54% vs LangGraph 62%

**Devin（号称首个 AI 软件工程师）**（来自 [OpenAIToolsHub 2026 review](https://www.openaitoolshub.org/en/blog/devin-ai-review)）：
- 2024 launch 自报 SWE-bench 13.86%
- Cognition **没有更新过 2025 / 2026 的 benchmark**
- 公认局限：模糊需求难处理、复杂任务容易钻牛角尖、关键操作必须人审

**LLM Agent 失败率研究**（来自 [Augment Code 2026 report](https://www.augmentcode.com/guides/why-multi-agent-llm-systems-fail-and-how-to-fix-them) 与 [arxiv 2601.16280](https://arxiv.org/abs/2601.16280)）：
- **生产环境多 agent 系统失败率：41-86.7%**
- Context 保留每步丢 2%，5 步循环后只剩 60% 原始上下文可访问
- 12 类工具调用错误分类法，小模型工具初始化是主瓶颈

**Unity AI 生态**（来自 [andrew.ooo Unity MCP guide](https://andrew.ooo/posts/unity-mcp-ai-game-development-bridge/) 与 [GitHub IvanMurzak/Unity-MCP](https://github.com/IvanMurzak/Unity-MCP)）：
- Unity MCP（独立项目）5800+ stars，把 Unity Editor 当成可寻址工具表面
- Unity 官方 AI Gateway 2026 年开始 roll out
- Coplay.dev 提供 Unity AI 助手，定位是"AI for Unity dev"而非全自主搭建
- **没有公开的"AI 一键搭 Unity 项目"产品**

**CrewAI Pydantic + Tool Calling 已知问题**（来自 CrewAI [GitHub issues](https://github.com/crewAIInc/crewAI/issues/1338)）：
- Pydantic schema 不被加入 system prompt 是已知 bug
- Gemini LLM tool calling 在 1.14 + LiteLLM 1.70 下 tools 参数被传 null
- LiteLLM 缺失依赖在 1.0.0 升级时大面积失败

---

## 九、技术局限性的诚实评估

把"模型层"、"框架层"、"目标层"分开评估。

### 模型层

| 模型 | 工具调用可靠性（本项目实测） |
|---|---|
| DeepSeek v4-flash (reasoner) | 不支持 tool_choice required；DSML token 5/5 泄漏（native）；ReAct 文本模式偶错格式 |
| Qwen-plus | 工具调用最稳；response_format json_schema 支持；tool_choice specific 模式 5/5 强制成功 |
| GLM-4-plus | 同 Qwen，文档稍弱 |
| MiMo v2.5-pro | 不稳定，2/5 trial 报 None/empty |

**结论**：模型在"单步骤工具调用"这件事上其实**有解**（Qwen + 正确配置）；问题是"多步骤工具编排 + 严格输出"的复合场景，所有模型都不可靠。这是当前 LLM 的**真实能力边界**，不是"哪家模型不行"。

### 框架层

CrewAI 1.14 的几个未公开缺陷（本项目实测）：
- `Task(output_pydantic=Spec)` 与 tool-using agent 不兼容
- LiteLLM Instructor / Converter 不继承 LLM 实例上的 api_key
- runtime 不自动从 llm_models 读 max_tokens
- ReAct 文本协议默认开启，没有"强制走 native tool_calls"开关
- per-call tool_choice 不在 Agent 公开 API 里

**对比 LangGraph**（基于公开资料）：
- LangGraph 的"图编排"更显式，节点之间状态传递可控
- 失败模式不同，但同样需要 workaround
- 代码生成基准上 LangGraph 62% vs CrewAI 54%，但都不到 70%

**结论**：CrewAI 在"快速搭多 agent demo"很顺手，但"生产级严谨输出"需要**自己加 server-side enforcement 层**。这部分工作量本项目证明可控（~7 层防御机制，没有任何一层是不可工程化的）。

### 目标层（最难的部分）

**"AI 一键产出 Unity 游戏" 这个产品目标在 2026 年是 stretch 目标**：

- 需要全局一致性（namespace、事件订阅链、prefab 引用）—— agent 在 max_iter 内维持不住
- 需要跨文件依赖管理 —— 当前 LLM context 衰减 5 步后只剩 60%（MemU 2026 数据）
- 需要 Unity Editor 交互验证 —— 即使 Unity MCP 暴露了 Editor，agent 没法"看见运行结果再调整"
- 需要美术资源生产 —— 这部分本项目走脚本化路径（`script_comfy_generate`）成功了，因为它本质上是确定性步骤

**对比 Devin / Cursor agent 模式 / 各家"AI 工程师"**：
- 没有任何一家做到"全程自主 + 高成功率"
- 主流姿态全部收敛回"AI 协助 + 人审 checkpoint"
- SWE-bench 13.86% 是 Devin 自报上限

---

## 十、未来方向与可能性

基于以上数据，给四个方向的判断：

**方向 1：降低自主度，加人审 checkpoint（推荐短期）**

每个 Crew 完成后弹"待审核"，用户瞄一眼放行/驳回。驳回带反馈词触发 re-run。这是**今天能落地的产品形态**——半小时 demo 一个游戏，用户操作的不是按钮而是"审核者"角色。

**方向 2：脚本化更多确定性步骤（推荐中期）**

本项目已有 `script_comfy_generate` 路径（图片生成）100% 可靠，因为它绕开 agent 直接 HTTP 调用 ComfyUI。类似可以延伸：
- 文件创建 / 目录结构 / .meta 生成 → 脚本
- Unity prefab 装配的常见 pattern → 脚本
- Asset import 配置 → 脚本

让 LLM 只做"决定写什么"，不直接"怎么写"。

**方向 3：等下一代模型自然变好（推荐 1-2 年视野）**

GPT-5 / Claude Opus 5 / Qwen3.7 / GLM-5 已经在路上，工具调用可靠性、长上下文一致性、Unity 领域知识都在指数提升。今天硬卷的 workaround 在下一代模型上可能全不需要。**ROI 计算**：投 3 个月做 100% 自主 vs 等 1 年模型自然到位 + 做半自主——后者通常更划算。

**方向 4：换 stack（高投入，长期价值不确定）**

可选项：
- Anthropic API + 自研编排（Computer Use / Code Execution tool 原生支持更好）
- LangGraph（图式编排更显式）
- 自研 minimal agent loop（最大控制权，最大维护成本）

**没有明显赢家**——CrewAI 的痛点在别的框架里以不同形式存在，主要的 trade-off 是"上手快 vs 极致控制"。

---

## 十一、结语：技术尝试值不值得做

如果你看完前面 1 万字觉得"这项目踩了一堆坑、目标也没完全达到，到底值不值"，我的回答是：

**值，但不是从产品意义上**。

从工程产出角度：
- 188 个 commits + 188 次失败/微调 = 一份对"CrewAI 在生产严谨场景的真实表现"的高保真观察
- 7 层防御机制 + 5 个 rescue 分支 = 一份"如何在不可靠 framework 上加 enforcement 层"的工程参考
- 5 次 PM 大改写 = "渐进富集 Pydantic 链 + Crew 池 + 代码契约"这个范式的实测数据
- 本会话的 N=5 × 5 provider 实验 = 一份可复用的 LLM 工具调用基准

从产品意义角度：**今天还做不出"一键 Unity 游戏"**。等下一代模型 + 持续打磨架构，可能 12-18 个月有机会。

**这是一篇失败学的文章**——失败学的价值在于让下一个走同样路的人少踩几个坑。如果你也在做"LLM 自主代码生成"类项目，希望本文里的 7 个防御机制清单、4 条弯路标记、Probe 数据，能省你几周时间。

---

## 参考资料

行业现状与对比：
- [CrewAI Hit 47.8K Stars and 2 Billion Agent Runs (DigitalbyDefault 2026)](https://digitalbydefault.ai/blog/crewai-multi-agent-orchestration-2026)
- [Best Multi-Agent Frameworks 2026 (Gurusup)](https://gurusup.com/blog/best-multi-agent-frameworks-2026)
- [Devin AI Review 2026 (OpenAIToolsHub)](https://www.openaitoolshub.org/en/blog/devin-ai-review)
- [Devin 1: Specs, Benchmarks & Why It's Obsolete (UC Strategies 2026)](https://ucstrategies.com/news/devin-1-specs-benchmarks-why-its-obsolete-2026/)

LLM Agent 失败模式研究：
- [When Agents Fail to Act: Diagnostic Framework (arxiv 2601.16280)](https://arxiv.org/abs/2601.16280)
- [Beyond pass@1: Reliability Science for Long-Horizon Agents (arxiv 2603.29231)](https://arxiv.org/html/2603.29231v1)
- [Multi-Agent AI Systems: Why They Fail (Augment Code 2026)](https://www.augmentcode.com/guides/why-multi-agent-llm-systems-fail-and-how-to-fix-them)
- [LLM Agentic Failure Modes (Ceaksan)](https://ceaksan.com/en/llm-agentic-failure-modes)
- [AI Agent Harness Failures: 13 Anti-Patterns (Atlan)](https://atlan.com/know/agent-harness-failures-anti-patterns/)

Unity AI / MCP 生态：
- [Unity MCP - AI Game Development Bridge (andrew.ooo)](https://andrew.ooo/posts/unity-mcp-ai-game-development-bridge/)
- [Unity-MCP GitHub (IvanMurzak)](https://github.com/IvanMurzak/Unity-MCP)
- [Advanced Agentic Game Development in Unity (Medium)](https://medium.com/@jengas/advanced-agentic-game-development-in-unity-with-mcp-5add91c579e9)
- [Coplay - AI Assistant for Unity Game Development](https://coplay.dev/)
- [Unity AI: AI Game Development Tools (Unity Official)](https://unity.com/features/ai)

CrewAI Pydantic / LiteLLM 已知问题：
- [CrewAI Issue #1338: Pydantic schema not in system prompt](https://github.com/crewAIInc/crewAI/issues/1338)
- [CrewAI Issue #2895: Gemini Tool Calling Fails with null tools](https://github.com/crewAIInc/crewAI/issues/2895)
- [CrewAI Discussion #1436: How to get structured output using pydantic](https://github.com/crewAIInc/crewAI/discussions/1436)

---

*作者注：本文数据基于 MyCrew 项目自 2026-04-22 至 2026-05-21 的实测，硬件环境 Windows 11 + Python 3.13 + CrewAI 1.14.4 + LiteLLM 1.85+。所有结论可在项目仓库的 `data/` 目录下的 diag_*.json 文件复现。欢迎技术交流。*
