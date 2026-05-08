# 0004. LLM 记录 = 1 provider+key 配多 model（嵌套表）

## Status

Accepted

## Context

MyCrew v3 需要支持多种 LLM 提供商（OpenAI、Anthropic、Qwen/通义千问、DeepSeek、本地 Ollama 等），每个提供商下可能有多个可用模型。我们需要设计一个灵活、清晰的数据模型来管理这些 LLM 配置。

考虑过的方案：

### 方案 A：扁平表
一张 `llm_configs` 表，每行存一个 (provider, api_key, model_name, base_url) 组合。

- 问题：同一个 provider 的 API Key 会重复存储多次（每个模型一行），更新 Key 需要修改多行
- 问题：无法清晰表达"一个提供商拥有多个模型"的层次关系

### 方案 B：JSON 嵌套
一张 `llm_providers` 表，模型列表以 JSON 数组存在 `models` 字段中。

- 问题：无法对单个模型建立外键引用（如 Agent 默认使用某个模型）
- 问题：JSON 字段内的模型无法参与 SQL 查询优化

### 方案 C：两级表（本决策）
`llm_providers` 表（1 条记录 = 1 个提供商 + API Key）+ `llm_models` 表（1:N，每个模型属于一个提供商）。

- 优点：数据规范化，API Key 不重复，模型可被独立引用
- 优点：可以通过外键将 Agent 的默认模型指向 `llm_models.id`

## Decision

采用两级嵌套表设计来管理 LLM 配置：

### `llm_providers` 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT (UUID) | 主键 |
| name | TEXT | 提供商名称（如 "OpenAI", "Anthropic"） |
| provider_type | TEXT | 类型标识（openai / anthropic / qwen / ollama / custom） |
| api_key_enc | BLOB | 加密存储的 API Key |
| base_url | TEXT | API 端点（可选，用于自定义/代理部署） |
| is_active | BOOLEAN | 是否启用 |

### `llm_models` 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT (UUID) | 主键 |
| provider_id | TEXT (FK) | 所属提供商 |
| model_name | TEXT | 模型标识（如 "gpt-4o", "claude-sonnet-4"） |
| display_name | TEXT | 前端显示名 |
| is_default_inception | BOOLEAN | 是否为 Inception（项目规划）默认模型 |
| is_default_agent | BOOLEAN | 是否为 Agent 执行默认模型 |

### 前端交互

UI 使用两级下拉选择器：

1. 第一级：选择 Provider（如 "OpenAI"）
2. 第二级：选择该 Provider 下的 Model（如 "gpt-4o"、"gpt-4o-mini"）

### 默认模型指针

系统维护两个默认模型指针：

- **Inception 默认**：用于项目规划（通常选择最强模型，如 claude-sonnet-4）
- **Agent 默认**：用于 Agent 日常执行（可选择性价比较高的模型）

Agent 可以单独覆盖默认模型选择。

## Consequences

**正面影响：**

- 数据模型清晰：一个 Key 对应一个提供商，不重复存储
- 模型可独立引用：Agent 可通过外键指向特定 `llm_models.id`
- 灵活扩展：添加新提供商只需插入 `llm_providers` 记录和对应的 `llm_models` 记录
- 支持自定义端点：`base_url` 字段允许用户使用 API 代理或私有部署

**负面影响：**

- 前端选择器略显复杂：两级下拉比单级下拉需要更多交互步骤
- 新用户首次配置需要先添加 Provider 再添加 Model，步骤稍多（可通过预设模板缓解）

**中性影响：**

- 两个默认指针（inception / agent）增加了灵活性，但也需要在 UI 中清晰解释其用途
- API Key 的加密存储（`api_key_enc`）与 Tauri Stronghold 集成，详见 ADR-001

## References

- plan.md §4（数据模型 - llm_providers / llm_models 表定义）
- plan.md §5（后端服务 - llm_svc 管理逻辑）
- plan.md §8（前端 - Settings 页面 LLM 配置 UI）
