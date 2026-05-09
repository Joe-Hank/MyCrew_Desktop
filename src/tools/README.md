# src/tools/

用户自定义 Tool 脚本（被 Agent 调用的能力）。

## 接口约定

每个 `.py` 文件应导出一个 `crewai.tools.BaseTool` 子类：

```python
# src/tools/my_tool.py
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

class MyToolArgs(BaseModel):
    query: str = Field(..., description="搜索关键词")
    top_k: int = Field(5, ge=1, le=20)

class MyTool(BaseTool):
    name: str = "my_search"
    description: str = "在本地知识库搜索相关条目"
    args_schema: type[BaseModel] = MyToolArgs

    def _run(self, query: str, top_k: int = 5) -> str:
        # 实现
        return result
```

后端启动 + 用户点"扫描 src/tools" → 自动发现并入库到 `tools` 表。

## 子目录划分

| 子目录 | 用途 |
|---|---|
| `toolCrafter/` | 创建自定义Tool的模板，开发人员用，与项目无关 |
| `builtin/` | 项目内置 Tool（与 MCP 服务器配套的手写包装） |
| 直接放本目录 | 用户/开发者自定义的"业务"Tool |

## 加载安全

- 首次发现新 Tool 时 WS 发 `tool.discovered` → 前端弹"信任并加载"二次确认
- checksum 变更后 WS 发 `tool.changed` → 前端弹"已更新，是否信任新版本？"
- 文件操作受 `permission_svc` 9 个权限开关短路控制
- 加载发生在 sidecar 进程内，**无独立沙箱**（plan §11.5 决策）

## 命名建议

- 单文件 Tool：`<功能>_tool.py`（如 `web_search_tool.py`）
- 复杂 Tool：建子目录，`<name>/__init__.py` 导出 BaseTool 子类
