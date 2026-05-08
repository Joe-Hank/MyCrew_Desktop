# backend/infra/llm/

LLM Port 的 Adapter 实现。

## 文件清单（Phase 2/4 落地）

| 文件 | provider |
|---|---|
| `base.py` | `BaseLLMAdapter`（共用：重试、超时、流式封装、structured output 提取） |
| `openai_adapter.py` | OpenAI 官方 SDK |
| `anthropic_adapter.py` | Anthropic 官方 SDK（含 prompt cache + thinking 模式） |
| `qwen_adapter.py` | Qwen / DashScope SDK |
| `deepseek_adapter.py` | DeepSeek（OpenAI 兼容） |
| `gemini_adapter.py` | Google Gemini SDK |
| `ollama_adapter.py` | Ollama（本地）|
| `custom_adapter.py` | OpenAI 兼容兜底（任意 base_url）|
| `registry.py` | provider 注册表（type 枚举 → Adapter 类映射） |

## 设计要点

- 所有 Adapter 接受同一份 `LlmConfig`（含 api_key / base_url / model_name / supports_thinking）
- 输出统一 `LlmResponse`（含 text / usage / finish_reason）
- 流式输出走 `AsyncIterator[LlmDelta]`
- structured output：优先用 provider 原生 JSON mode；不支持的 fallback 到 prompt 工程

## Token 用量探活

- `get_quota(provider) → QuotaInfo` 各 Adapter 实现
- 不返回额度也不可查询的 provider（如 Anthropic）：派一次 1-token 最小请求 → 成功亮绿点 / 失败亮红点
- 30s TTL 缓存；用户手动刷新强制重新探活

## 凭证

- Adapter 不持久化 key；每次调 `secret_port.get_secret(provider_id)` 拉取
- key 出栈即丢，不进日志（structlog 中间件统一脱敏）
