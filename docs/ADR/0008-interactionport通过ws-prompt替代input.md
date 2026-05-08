# 0008. InteractionPort 通过 WS prompt.request/response 替代 input()

## Status

Accepted

## Context

CrewAI 框架支持"Human Input"（人工输入）功能：当 Agent 在执行任务过程中需要人类确认、选择或补充信息时，可以暂停执行并请求输入。CrewAI 的默认实现使用 Python 内置的 `input()` 函数，这在终端应用中可以正常工作。

但在 MyCrew v3 的架构中，这种方式完全不可行：

1. **阻塞问题**：`input()` 会阻塞整个 Python 线程，无法响应其他请求
2. **无 GUI 交互**：`input()` 从 stdin 读取，桌面应用的前端（WebView）无法与之交互
3. **无超时机制**：如果用户离开电脑，`input()` 会永久阻塞
4. **无审计能力**：`input()` 的交互过程没有记录

我们需要一个异步、非阻塞、与 GUI 集成的人机交互方案。

### 设计灵感

参考了以下模式：

- **VS Code 的 InputBox API**：通过消息传递请求用户输入，返回 Promise
- **GitHub Actions 的 Manual Approval**：异步等待人工审批，带超时
- **RPC Request-Response 模式**：每个请求携带唯一 ID，响应通过 ID 关联

## Decision

定义 `InteractionPort` 协议接口，通过 WebSocket 的 `prompt.request` / `prompt.response` 消息对实现异步人机交互。

### InteractionPort 协议

```python
from typing import Protocol

class InteractionPort(Protocol):
    async def prompt_choice(
        self,
        message: str,
        choices: list[str],
        timeout_seconds: int = 300,
    ) -> str:
        """请求用户从选项中选择"""
        ...

    async def prompt_text(
        self,
        message: str,
        placeholder: str = "",
        timeout_seconds: int = 300,
    ) -> str:
        """请求用户输入文本"""
        ...

    async def prompt_confirm(
        self,
        message: str,
        timeout_seconds: int = 120,
    ) -> bool:
        """请求用户确认（是/否）"""
        ...
```

### WebSocket 实现流程

```
┌────────────┐                          ┌────────────┐
│  Python     │   prompt.request         │  Frontend  │
│  Backend    │ ─────────────────────►   │  (React)   │
│             │   {                      │            │
│  await      │     request_id: "abc",   │  显示对话框  │
│  future     │     type: "choice",      │            │
│             │     message: "选择...",    │  用户操作    │
│             │     choices: [...]        │            │
│             │   }                      │            │
│             │                          │            │
│             │   prompt.response        │            │
│  resolve    │ ◄─────────────────────   │            │
│  future     │   {                      │            │
│             │     request_id: "abc",   │            │
│             │     value: "选项A"        │            │
│             │   }                      │            │
└────────────┘                          └────────────┘
```

### 详细实现

1. **请求发起**：当 Agent 触发人工输入时，`InteractionPort` 的 WS 实现生成唯一 `request_id`，创建 `asyncio.Future`，通过 WebSocket 发送 `prompt.request` 消息

2. **前端展示**：React 前端收到 `prompt.request` 后，根据 `type` 字段渲染对应的交互组件：
   - `choice` → 选项按钮组
   - `text` → 文本输入框
   - `confirm` → 确认/取消按钮

3. **用户响应**：用户操作后，前端发送 `prompt.response` 消息，携带 `request_id` 和用户输入的 `value`

4. **Future 解析**：后端收到 `prompt.response`，通过 `request_id` 找到对应的 `Future` 并 resolve，Agent 继续执行

### 超时与断线处理

- **超时**：每个请求携带 `timeout_seconds`，超时后 Future 抛出 `InteractionTimeoutError`，Agent 可选择使用默认值或终止任务
- **WebSocket 断线**：如果前端断线，所有 pending 的 Future 被标记为断线状态；前端重连后，后端重新发送所有 pending 的 `prompt.request`
- **多窗口**：如果有多个前端窗口连接，`prompt.request` 广播到所有窗口，第一个 `prompt.response` 生效

### 审计记录

每次交互记录到 `prompt_audit` 表：

| 字段 | 说明 |
|------|------|
| request_id | 请求唯一标识 |
| project_id | 所属项目 |
| task_id | 触发交互的任务 |
| agent_id | 触发交互的 Agent |
| prompt_type | choice / text / confirm |
| message | 提问内容 |
| response_value | 用户回答 |
| response_time_ms | 响应耗时（毫秒） |
| timed_out | 是否超时 |

## Consequences

**正面影响：**

- 完全异步、非阻塞：不会卡死后端线程，与 GUI 架构完美契合
- UI 集成友好：前端可以用丰富的交互组件（按钮、输入框、下拉菜单）替代纯文本 input()
- 可审计：所有人机交互都有完整记录，便于回溯和分析
- 超时安全：避免因用户长时间未响应导致 Agent 永久挂起
- 断线恢复：前端重连后可恢复 pending 的交互请求

**负面影响：**

- 实现复杂度高于简单的 `input()`：需要管理 Future 池、超时定时器、断线重连逻辑
- 前端需要实现通用的 prompt 渲染组件，支持多种交互类型
- 调试难度增加：涉及 WebSocket 消息收发、Future 状态管理等异步逻辑

**中性影响：**

- 相同的 `InteractionPort` 协议可复用于所有需要人工介入的场景（不仅限于 CrewAI 的 Human Input）
- `prompt_audit` 表数据可用于后续的"交互模式分析"——例如自动学习用户偏好以减少交互次数

## References

- plan.md §5（后端服务 - interaction_svc / InteractionPort 定义）
- plan.md §6（WebSocket 协议 - prompt.request / prompt.response 消息格式）
- plan.md §8（前端 - PromptDialog 组件设计）
- plan.md §10（测试策略 - InteractionPort mock 测试）
