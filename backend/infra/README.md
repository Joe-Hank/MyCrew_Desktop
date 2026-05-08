# backend/infra/

数据/集成层：Port 的具体 Adapter 实现。

## 子目录

| 子目录 | Adapter 实现的 Port |
|---|---|
| `llm/` | `LLMPort`：openai / anthropic / qwen / deepseek / gemini / ollama / custom（OpenAI 兼容兜底） |
| `mcp/` | `MCPPort`：stdio_client + http_client + pool（生命周期/心跳/重连） |
| `repo/` | `RepoPort`：sqlite_repo + file_repo |
| `interaction/` | `InteractionPort`：ws_interaction（通过 WS 双向消息，替代 input()） |
| `event_bus/` | `EventBusPort`：inproc_bus（进程内 pub/sub） |

## 关键约束

- infra 实现 Port 时**不要回写领域逻辑**——只做翻译（领域类型 ↔ 三方 SDK 类型）
- 一个 Adapter = 一个文件（小型）或一个子目录（大型，如 mcp）
- LLM Adapter 共用 base class 抽出公共逻辑（重试、流式、structured output）；各 provider 子类只填 SDK 调用细节

## 添加新 LLM provider

1. 在 `llm/` 下加 `xxx_adapter.py`，继承 `BaseLLMAdapter`
2. 在 `bootstrap/container.py` 注册到 `LlmProviderRegistry`
3. 设置页 `LLM 类型` 枚举追加（前端 + 后端）
4. 写单元测试（Mock SDK 响应）

## 添加新 MCP server 适配

MCP 走标准协议，**不需要写 Adapter**；只需在 `src/tools/builtin/mcp_<server>/` 下写 BaseTool 包装即可（这是用户/开发的事）。
