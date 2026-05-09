# MyCrew v3 实施进度 — 2026-05-09

## 已完成 Phase

| Phase | 说明 | 状态 |
|-------|------|------|
| 0-2 | 骨架 + 配置/凭据 + 启动加载 | ✅ committed |
| 3 | MCP 连接池 + 首批包装 Tool | ✅ committed |
| 4 | Harness 领域核心（状态机/DAG/事件总线/交互端口） | ✅ committed |
| 5 | 主页 + 立项全流程（ProjectGrid/InceptionDrawer/会话历史/蓝图编辑） | ✅ committed |
| 6 | 任务页（DAG 蓝图/ProjectHeader/TaskNode/IO 查看器/Agent 对话） | ✅ committed |
| 7 | 团队页（Agent/Crew/Tool 三 Tab + EditorDrawer） | ✅ committed |
| 8 | 设置页完善 + 权限拦截 + 视觉对齐 | ✅ committed |
| 9 | 打磨与打包（主题/错误边界/PyInstaller/Tauri sidecar） | ✅ committed |
| 10 | Figma 原型对齐（设置页/团队页/主页 → 药丸Tab+表格+底部状态栏） | ✅ committed |
| 11 | LLM Gateway + 真实 LLM 调用接入 | ✅ committed |

## Phase 11 新增/修改文件

### 新增
- `backend/infra/llm/__init__.py` — LLM 基础设施包入口，导出所有类型和 gateway 单例
- `backend/infra/llm/base.py` — 基础类型（LlmConfig/LlmMessage/LlmResponse/LlmDelta/LlmUsage）+ 抽象基类 BaseLLMAdapter（含重试/超时逻辑）
- `backend/infra/llm/openai_adapter.py` — OpenAI 兼容适配器（覆盖 OpenAI/DeepSeek/Qwen/Gemini/Ollama/Custom），使用 httpx 直接调用
- `backend/infra/llm/anthropic_adapter.py` — Anthropic Claude 适配器（支持 extended thinking 模式）
- `backend/infra/llm/registry.py` — Provider type → Adapter class 注册表
- `backend/infra/llm/gateway.py` — LlmGateway 单例（统一入口：chat/stream/chat_json/check_availability），按 (provider_id, model_name) 缓存 adapter 实例

### 修改
- `backend/services/inception_svc.py` — 替换 mock `_call_llm` 为真实 LLM 调用；新增 `stream_message` 流式方法；新增 `_build_messages`/`_resolve_llm`/`_get_default_inception_llm` 辅助方法；finalize 时自动补 final_qa task
- `backend/services/workflow_svc.py` — 替换 placeholder `_run_agent` 为真实 Agent LLM 调用（构建 system prompt + task prompt + upstream context）；替换 placeholder `_extract_structured_output` 为三级提取策略（直接 JSON 解析 → markdown JSON 块 → LLM JSON mode 提取）；新增 `_resolve_agent_llm` 方法
- `backend/services/llm_svc.py` — `get_quota` 方法改为调用 `llm_gateway.check_availability` 做真实探活

## 架构要点

### LLM 调用链路
```
inception_svc / workflow_svc
    → llm_gateway.chat(provider_id, model_name, messages)
        → registry.create_adapter(config)
            → OpenAICompatibleAdapter / AnthropicAdapter
                → httpx POST to provider API
```

### 支持的 Provider 类型
| type | 适配器 | 默认 Base URL |
|------|--------|--------------|
| openai | OpenAICompatibleAdapter | api.openai.com/v1 |
| deepseek | OpenAICompatibleAdapter | api.deepseek.com/v1 |
| qwen | OpenAICompatibleAdapter | dashscope.aliyuncs.com/compatible-mode/v1 |
| gemini | OpenAICompatibleAdapter | generativelanguage.googleapis.com/v1beta/openai |
| ollama | OpenAICompatibleAdapter | localhost:11434/v1 |
| custom | OpenAICompatibleAdapter | 用户自定义 |
| anthropic | AnthropicAdapter | api.anthropic.com/v1 |

### 结构化输出提取策略（三级）
1. 直接 `json.loads(raw_text)` — Agent 直接输出 JSON 时命中
2. 正则提取 ` ```json ... ``` ` 代码块 — Agent 用 markdown 包裹 JSON 时命中
3. LLM JSON mode 二次调用 — 以上都失败时，用同一 LLM 做结构化提取

## 当前统计
- 后端 65+ API routes
- 前端 tsc 零错误
- 所有 Phase 0-11 已 commit 并 push 到 `origin/main`

## 下一步可选工作
- 实际 PyInstaller 打包验证
- cargo tauri build 出安装包
- 端到端联调测试（启动后端 + 前端，配置 LLM，跑一次完整立项→执行流程）
- 补充后端单元测试（pytest）
