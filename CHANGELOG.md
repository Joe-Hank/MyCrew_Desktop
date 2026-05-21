# Changelog

本文件记录 MyCrew_v3 的版本变更，遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范。

---

## [Public Release] - 2026-05-21

### 项目状态变更

- 🌍 **仓库从 PRIVATE 改为 PUBLIC**
- 📜 **License 从 MIT 替换为 PolyForm Noncommercial 1.0.0**（允许个人 / 研究 / 教育用途，禁止商用）
- 📂 同步发布两篇技术复盘文章（见下方 `docs/` 部分）

### Added — 新增

**架构层**
- `backend/domain/crew_specs.py` —— Pydantic Spec 注册表（per-Crew/per-step），为框架级 schema 强制留口子（出于 Phase 4 实测原因暂未启用 `Task(output_pydantic=)`）
- `backend/src/tools/builtin/local/verify_outputs.py` —— Layer 2 落盘自检工具（自动注入到非 head 步骤）
- `backend/services/workflow_svc._check_claimed_paths_on_disk()` —— server-side 磁盘真相校验（抓 agent 编造 file_paths 的作弊）

**诊断脚本**（`backend/scripts/diag_*.py`）—— 全部保留为可复用资产：
- `diag_forced_tool_choice.py` —— DeepSeek tool_choice 兼容性探测
- `diag_crewai_executor_repro.py` —— CrewAI executor 真实失败模式 trace
- `diag_native_vs_litellm.py` —— native vs litellm 路径对照
- `diag_response_format_compat.py` —— 4 provider × 3 mode 兼容性矩阵
- `diag_probe1_converter_success.py` —— `output_pydantic` 首次成功率
- `diag_probe2_tool_choice.py` —— tool_choice 强制行为 N=5
- `diag_phase4_variants.py` —— 5 变量 × 5 trial 受控对照
- `diag_layer1_layer2_integration.py` —— Layer 1+2 端到端集成
- `reset_fruit_ninja_stale_done.py` —— 清理"假成功"task（status=done 但文件不存在）

**测试**
- 7 个新单元测试覆盖 `_check_claimed_paths_on_disk`
- 2 个新单元测试覆盖 `_rescue_react_emit_output` 的 OpenAI wire-shape unwrap 分支

**文档**
- `docs/retrospective_v1_to_v3.md` —— **5500 字技术复盘文章**（CSDN 风格，含 v1→v2→v3 + PM 5 次重写 + 实验数据 + 行业对比 + 12 篇参考资料链接）
- `docs/personal_journey_short.md` —— **1500 字经历总结**（求职 / 合作方向，含 CrewAI 边界判断 + 轻量化转型方向）

### Changed — 改动

**LLM 路由 & 调优**
- `crewai_runner._build_crewai_llm()` —— 自动将 `api_key` 桥接到 provider 对应 env var（修 CrewAI Converter/Instructor 不继承 api_key 的工程坑）
- `crewai_runner.run_crew_step_with_crewai()` —— 从 `llm_models` 表自动读 `max_tokens` 传给 LLM（之前 None → LiteLLM 默认 ~1500 tok → 长 spec 被截断）
- 4 个 agent 的 `llm_id` 切换到 Qwen：`Unity Developer` / `QA Engineer` / `System Designer` / `UI/UX Designer`（Phase 4 实测 Qwen 工具调用率 ≫ DeepSeek）
- `llm_models.max_tokens` 批量设到 8192（qwen-plus / qwen-max / qwen-coder-plus / deepseek-v4-flash / deepseek-v4-pro）

**Rescue & 错误信息**
- `_rescue_react_emit_output` 新增 OpenAI tool-call wire-shape 分支（识别 `{"name": "emit_output", "arguments": {"payload": ...}}` 并解包 2 层）
- "Crew step 没有调用 emit_output" 错误信息升级为 4 类诊断 + raw_text 头尾片段（之前只说"没调用"，用户得自己翻 sub/*.json）
- `crew.empty_captured_halt` log 字段新增 `raw_len` / `raw_excerpt_head` / `raw_excerpt_tail` / `likely_truncated`

### Discovered — 实测发现（影响设计方向）

- 🔴 **`Task(output_pydantic=Spec)` 与 Qwen 的 tool-using agent 不兼容**：N=5 × 5 变量 受控实验，4 个 output_pydantic 变量 0/5 写文件，唯一 no_pydantic 5/5。Phase 4 finding 已写入 `docs/retrospective_v1_to_v3.md`。
- 🔴 **DeepSeek reasoner 不支持 `tool_choice="required"` 和具体函数指定**：API 直接 400。仅支持 `"auto"`。
- 🟢 **Qwen 支持 `tool_choice={"type":"function","function":{"name":"X"}}` 精确强制**：N=5 全部 5/5 强制成功。
- 🟢 **Server-side disk truth check 是必要的**：实测 agent 100% 作弊率（编 file_paths 不写文件），server-side 100% 抓获率。

### Removed — 撤销

- Layer 1 的 `Task(output_pydantic=Spec)` 运行时 wiring（受 Phase 4 实测推翻；`crew_specs.py` 保留作 server-side 校验 + 文档）

### Project Pivot — 方向转型

项目从"AI 全自主 Unity 游戏搭建"调整为"**适合 CrewAI 跑稳的轻量化场景**"——具体目标方向：
- AI 漫剧剧本生成（多 agent 协作产出角色 + 分镜 + 对白）
- 自动化 PPT 制作（拆章节 → 写大纲 → 调图像 API → 装配）
- AI 内容创作类（营销文案 / 自媒体 / PRD 草稿）

底层基础设施（PM 多阶段拆解 / Crew 池 / 可视化看板 / 多模型路由 / 防御层）原样迁移。同时持续跟进新模型新框架。

详见 `docs/personal_journey_short.md`。

---

## Previous History

详见 git log。关键 milestone：

- **2026-05-09** Phase 0：项目脚手架（Tauri 2.x + React 19 + FastAPI sidecar）
- **2026-05-13** Phase 17：Plan Maker 集成（CrewAI agent + create_workflow tool）
- **2026-05-15** PM v3：渐进富集 Pydantic 链（ConceptDoc → AtomicTask → ReviewedTask → PathedTask → Assignment）
- **2026-05-15** Plan Maker v2：Dify 风格意图路由 + 5 子 agent（token 经济 -75% ~ -96%）
- **2026-05-16** PM v4：8 Crew 池 + 14 单职责 Agent + performer schema
- **2026-05-17** PM v5：code_contract phase + regex verifier
- **2026-05-18** code_contract 校验从 regex 升级到 tree-sitter AST 语义匹配
- **2026-05-19** Stage D：契约缺签名时 Debugger 精准补丁
- **2026-05-19** 强制 `is_litellm=True` 绕开 CrewAI 1.14 deepseek native bug
- **2026-05-21** Layer 1+2 架构重构 + 公开发布
