# src/tools/toolCrafter/

**自定义 Tool 模板库**。提供开箱即用的 CrewAI Tool 骨架，供用户/开发者复制后填入业务逻辑。

> 目标：遵循 **crewai 最新版（0.100+）** 的 Tool API 契约，覆盖所有可配置项，并在文件内用注释明确区分「核心配置项」与「可选配置项」。

---

## 三种模板规格

CrewAI 官方共支持三种定义 Tool 的方式，本目录为每种方式提供一个模板文件：

| 模板文件 | 对应 CrewAI API | 适用场景 |
|---|---|---|
| `template_base_tool.py` | `crewai.tools.BaseTool` 子类 | **默认首选**。完整掌控 name/description/args_schema/caching/usage limit/result_as_answer/异步等全部能力，适合中到高复杂度 Tool。 |
| `template_decorator_tool.py` | `@crewai.tools.tool` 装饰器 | 轻量级。用装饰器把普通函数变成 Tool，适合逻辑简单、无需缓存/用量限制/复杂 schema 的场景。 |
| `template_structured_tool.py` | `crewai.tools.structured_tool.CrewStructuredTool` | 需要 **严格 Pydantic 校验 + LangChain 互操作** 的场景（例如把已有 LangChain Tool 迁入 CrewAI，或工具要对接外部编排框架）。 |

> 不确定选哪个？用 `template_base_tool.py`。

---

## 快速上手

1. **复制** 目标模板文件到 `src/tools/` 或 `src/tools/builtin/` 下，按命名约定重命名（如 `web_search_tool.py`）。
2. **删除**模板中所有带 `# TEMPLATE:` 前缀的占位注释/示例字段。
3. **按需填写**「核心配置项」区块（必填）。
4. **按需启用**「可选配置项」区块（不用的留空或直接删除）。
5. **实现** `_run()`（或装饰器函数体）里的业务逻辑。
6. 后端启动后点击"扫描 src/tools"，新 Tool 会被自动发现并入库。

---

## 配置项速查

### 核心配置项（必填）

- `name: str` —— Tool 在 Agent 视角下的唯一标识，**同进程内必须唯一**。只能 `[a-zA-Z0-9_]`，建议 snake_case。
- `description: str` —— Tool 的能力描述，**直接进 LLM prompt**，决定 Agent 是否调用此工具。必须写清楚：做什么 / 什么时候用 / 输入输出是什么。
- `_run(self, **kwargs) -> Any` —— 同步执行体。返回值会被 CrewAI 序列化成字符串喂给 LLM。

### 可选配置项

- `args_schema: type[BaseModel]` —— Pydantic 输入 schema，不写则由 CrewAI 从 `_run` 签名推断；**复杂/高风险 Tool 强烈建议显式写**以确保参数校验。
- `cache_function: Callable[[dict, Any], bool]` —— 判断本次调用是否命中缓存；默认全部缓存。返回 `False` 则本次结果不进缓存。
- `result_as_answer: bool` —— 设为 `True` 时 Agent 不再把 Tool 结果交给 LLM "再润色"，直接作为 task 最终输出（适合报表类、文件路径类 Tool）。
- `max_usage_count: int` —— 单 task 内本 Tool 最多被调用次数（防死循环）。
- `current_usage_count: int` —— 内部计数器，通常不手动设置。
- `description_updated: bool` —— 内部状态位，Agent 运行时动态修改 description 后会被置 `True`。通常不手动设置。
- `_arun(self, **kwargs) -> Any` —— 异步执行体；定义后 CrewAI 会优先调用异步版本。

### 不属于 Tool 本身、但在使用 Tool 时可以设置的

- Agent 层：`Agent(..., tools=[...], tool_choice="auto" | "required" | "none")`
- Task 层：`Task(..., tools=[...])` 覆盖 Agent 默认工具集
- 全局：`crewai.Crew(..., memory=True, cache=True)` 才能真正激活 `cache_function`

---

## 安全与加载

- 本目录下的 `.py` 文件 **不会** 被后端扫描（被路径排除在 Tool 发现之外），纯粹是模板素材。
- 用户应把模板**另存**到 `src/tools/` 或 `src/tools/builtin/` 下再编辑。
- 新发现 Tool 时 WS 会推 `tool.discovered` → 前端弹"信任并加载"二次确认（详见 `src/tools/README.md`）。

---

## 参考

- CrewAI 官方文档: https://docs.crewai.com/concepts/tools
- BaseTool 源码: https://github.com/crewAIInc/crewAI/blob/main/src/crewai/tools/base_tool.py
- Pydantic v2: https://docs.pydantic.dev/latest/
