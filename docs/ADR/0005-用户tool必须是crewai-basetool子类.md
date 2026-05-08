# 0005. 用户 Tool 必须是 CrewAI BaseTool 子类

## Status

Accepted

## Context

MyCrew v3 需要一个插件协议，允许用户自定义 Tool（工具）供 Agent 在执行任务时调用。Tool 的典型场景包括：网页搜索、文件读写、API 调用、数据库查询等。

我们评估了三种插件协议方案：

### 方案 A：自定义 MANIFEST 格式
定义一个自有的 `tool.manifest.json`，描述 Tool 的名称、描述、参数、入口函数等。

- 优点：完全自主，不依赖第三方框架
- 缺点：需要自研参数校验、序列化、错误处理等基础设施；与 CrewAI 集成需要额外适配层

### 方案 B：通用 Python 可调用对象
任何 `Callable` 即可作为 Tool，通过类型注解推断参数。

- 优点：对用户最灵活，门槛最低
- 缺点：缺乏统一的参数校验、描述格式、错误处理约定；CrewAI 内部仍需包装为 BaseTool

### 方案 C：CrewAI BaseTool 子类（本决策）
所有用户 Tool 必须继承 `crewai.tools.BaseTool`，并通过 Pydantic 的 `args_schema` 定义参数。

- 优点：与 CrewAI 框架零摩擦集成，参数校验内置，接口一致
- 缺点：与 CrewAI 版本绑定，用户需了解 BaseTool API

## Decision

所有用户自定义 Tool 必须是 `crewai.tools.BaseTool` 的子类，并提供 `args_schema`（Pydantic BaseModel）。

### 具体要求

```python
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

class MyToolInput(BaseModel):
    query: str = Field(..., description="搜索关键词")
    max_results: int = Field(default=10, description="最大结果数")

class MyTool(BaseTool):
    name: str = "my_tool"
    description: str = "执行某种操作的工具"
    args_schema: type[BaseModel] = MyToolInput

    def _run(self, query: str, max_results: int = 10) -> str:
        # 工具实现逻辑
        return "result"
```

### 发现与加载机制

1. **扫描路径**：后端启动时扫描 `src/tools/` 目录下的所有 `.py` 文件
2. **反射发现**：动态导入每个模块，通过反射找到所有 `BaseTool` 子类
3. **元信息提取**：从类定义中提取 `name`、`description`、`args_schema` 等元信息
4. **注册入库**：将 Tool 元信息注册到数据库 `tools` 表，供前端展示和项目配置引用

### 安全机制

- **文件校验和（Checksum）**：每个 Tool 文件首次加载时计算 SHA-256 校验和并存储
- **变更检测**：后续启动时对比校验和，如有变更则标记并提示用户确认信任
- **信任确认**：用户在 UI 中确认信任后，更新校验和记录

## Consequences

**正面影响：**

- 与 CrewAI 框架直接集成，无需编写适配层或包装器
- Pydantic 提供自动参数校验、类型转换、错误消息，用户无需手动处理
- 统一的接口约定使得所有 Tool 具有一致的行为模式（名称、描述、参数、返回值）
- 前端可以根据 `args_schema` 自动生成 Tool 参数编辑表单

**负面影响：**

- 与 CrewAI 版本紧耦合：如果 CrewAI 更新 BaseTool API，用户 Tool 可能需要适配
- 用户需要学习 CrewAI BaseTool 和 Pydantic BaseModel 的基本用法，有一定学习曲线
- 不支持非 Python 语言编写的 Tool（如 Node.js、Shell 脚本），需通过 Python 包装器间接调用

**中性影响：**

- 校验和 + 信任确认机制在安全性和便利性之间取得平衡
- 未来如果 CrewAI 引入新的 Tool 协议（如 MCP Tool），可以在此基础上扩展兼容

## References

- plan.md §4（数据模型 - tools 表定义）
- plan.md §5（后端服务 - tool_svc 扫描与加载逻辑）
- plan.md §7（安全考量 - Tool 信任机制）
- plan.md §9（开发者体验 - Tool 开发指南）
