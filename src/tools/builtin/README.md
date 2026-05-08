# src/tools/builtin/

**MCP 包装 Tool 与项目内置 Tool**。

## 设计意图（v2 痛点 ② 的核心解决方案）

v2 直接把 MCP 服务器动态注入 CrewAI Agent，导致 Agent 调用 MCP 工具时参数频繁报错（CrewAI 的 dynamic MCP wrapper 在边界场景失准）。

v3 改为**手工 BaseTool 包装**：每个 MCP 工具一对一对应一个 BaseTool 子类，args_schema 严格按 MCP 官方文档定义，参数错误在 Pydantic 校验阶段就拦截。

## 目录组织约定

```
builtin/
├─ mcp_<server_name>/         一个 MCP 服务器一个子目录
│  ├─ __init__.py             导出该服务器下的所有 BaseTool 子类
│  ├─ <tool_name>.py          一个 MCP 工具一个文件
│  └─ README.md               记录该 server 的官方文档链接 + 包装进度
└─ <自定义内置功能>.py         不针对特定 MCP 的内置 Tool（如 file_indexer）
```

## 包装 Tool 示例

```python
# src/tools/builtin/mcp_blender/execute_code.py
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from backend.api.routes_mcp import internal_call  # 通过 loopback 调用

class ExecuteBlenderCodeArgs(BaseModel):
    code: str = Field(..., description="Python code to execute in Blender")

class ExecuteBlenderCode(BaseTool):
    name: str = "execute_blender_code"
    description: str = "Execute arbitrary Python in Blender's runtime"
    args_schema: type[BaseModel] = ExecuteBlenderCodeArgs

    def _run(self, code: str) -> str:
        return internal_call(server="blender", tool="execute_blender_code", args={"code": code})
```

## 待确认细节（首批包装哪些 MCP）

> 以下需在 Phase 3 开工时与用户确认，落定后追加到本 README 末尾。

**候选**（按 v2 经验和常用度排序）：

1. **Filesystem MCP**（`@modelcontextprotocol/server-filesystem`）—— 几乎所有项目都需要文件读写
2. **Blender MCP**（`uvx blender-mcp`）—— 3D 建模相关项目
3. **Figma MCP**（`https://mcp.figma.com/mcp`）—— 已在本对话中验证可用
4. **Notion MCP**（`https://mcp.notion.com/mcp`）—— 已在本对话中验证可用
5. **GitHub MCP**（条件：`GITHUB_TOKEN` 设置后）—— 代码相关项目
6. **Tavily MCP**（条件：`TAVILY_API_KEY` 设置后）—— 网络搜索

**Phase 3 必做**：选 2 个最常用 MCP（建议 1 + 2 或 1 + 3）作为首批示范，落地 BaseTool 包装模板与"生成包装骨架"按钮逻辑（基于 `mcp_servers.discovered_tools` 自动产 Pydantic 草稿）。

**未确认事项**：
- 首批选哪 2 个 MCP（用户 Phase 3 开工前拍板）
- Filesystem MCP 的 `allowed_dirs` 参数默认值（建议默认 `<project_root>` + `<MyCrew root>/data` + `<MyCrew root>/output`）
- 是否在 builtin 内做"包装 Tool 共享 base class"（如 `McpWrapperBase` 自动处理 `internal_call` 调用 + 错误转译）—— 第二个包装 Tool 写完后再决定，避免过早抽象

## 与团队页 Tools tab 的关系

- 本目录所有 BaseTool 子类来源标记 `source=builtin`，徽章 `builtin`
- 与用户在 `src/tools/` 直接放的脚本（来源 `user`）一同显示
- MCP 服务器的"已包装 K / 已发现 N"统计基于本目录的 `mcp_<server>/` 数量与 `mcp_servers.discovered_tools` 比对
