# backend/ports/

端口层：领域/服务通过 Protocol 接口与外界交互。

## 设计原则（依赖倒置）

- **Port 在领域圈内**：定义"我需要什么能力"
- **Adapter 在 infra**：定义"用什么具体技术实现"
- service 通过 DI 容器拿到 Port 实例（运行时是某个 Adapter）
- 测试时直接 Mock Port，不需要 Mock 三方库

## Port 清单

| 文件 | 接口 | 作用 |
|---|---|---|
| `llm_port.py` | `LLMPort` | 统一 LLM 调用接口：`chat(messages, model, temperature) → str`；流式版本 `chat_stream`；structured output `chat_structured(schema)` |
| `mcp_port.py` | `MCPPort` | MCP 调用：`call(server_id, tool_name, args) → result`；状态查询 `list_servers()` `get_status(id)` |
| `repo_port.py` | `RepoPort` (多个) | 数据访问抽象：`ProjectRepo` / `TaskRepo` / `AgentRepo` 等，每个实体一个接口 |
| `interaction_port.py` | `InteractionPort` | 用户介入：`prompt_choice` / `prompt_text` / `prompt_confirm`；替代 `input()` |
| `event_bus_port.py` | `EventBusPort` | 进程内 pub/sub：`publish(event)` / `subscribe(type, handler)` |
| `secret_port.py` | `SecretPort` | 凭证拉取：`get_secret(key) → str`；实现走 loopback HTTP 找 Tauri Stronghold |

## 严格约束

- Port 只用 typing.Protocol（结构化子类型，不强制继承）
- Port 方法的输入输出**只用领域类型**（dataclass / Pydantic）；不能出现 sqlalchemy / openai SDK 类型
- Port 不能依赖 infra / services；只能被 domain / services 依赖
