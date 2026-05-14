# Unity MCP 工具集

通过 [MCP for Unity](https://github.com/CoplayDev/unity-mcp) Bridge 完全控制 Unity Editor 的 34 个结构化工具。

## 快速开始

### 1. 安装 Unity 端

在 Unity Editor 中通过 Package Manager 安装 `com.coplay.mcpforunity`：
- Git URL: `https://github.com/CoplayDev/unity-mcp.git?path=unity-mcp-ts/Packages/com.coplay.mcpforunity`

### 2. 启动 MCP Server

安装后 Unity 会自动启动 MCP Server，默认监听 `http://127.0.0.1:8090/mcp`。

### 3. 配置连接

编辑 `data/config/unity_mcp.yaml`：

```yaml
unity_mcp:
  url: "http://127.0.0.1:8090/mcp"
```

或通过环境变量：

```bash
set UNITY_MCP_URL=http://127.0.0.1:8090/mcp
```

### 4. 使用工具

```python
from src.tools.builtin.unity import ALL_TOOLS, manage_gameobject_tool

# 注册全部 34 个工具到 Agent
agent = Agent(role="Unity Developer", tools=ALL_TOOLS)

# 或选择性注册
from src.tools.builtin.unity import (
    manage_scene_tool,
    manage_gameobject_tool,
    create_script_tool,
)
agent = Agent(role="Unity Developer", tools=[manage_scene_tool, manage_gameobject_tool, create_script_tool])
```

## 工具清单 (34 个)

| 分类 | 工具 | 说明 |
|------|------|------|
| **Infrastructure** | `batch_execute` | 批量执行多个命令 (10-100x 更快) |
| | `set_active_instance` | 多实例路由 |
| | `refresh_unity` | 刷新 Asset Database / 编译 |
| | `manage_tools` | 启用/禁用工具组 |
| **Scene** | `manage_scene` | 场景 CRUD、层级查询、截图 |
| | `find_gameobjects` | 搜索 GameObjects |
| **GameObject** | `manage_gameobject` | 创建/修改/删除/复制/移动 GO |
| | `manage_components` | 添加/移除/设置组件属性 |
| **Script** | `create_script` | 创建 C# 脚本 |
| | `script_apply_edits` | 结构化脚本编辑 |
| | `apply_text_edits` | 精确字符位置编辑 |
| | `validate_script` | 语法/语义检查 |
| | `get_sha` | 获取文件哈希 |
| | `delete_script` | 删除脚本 |
| **Asset** | `manage_asset` | 资产搜索/创建/移动/删除 |
| | `manage_prefabs` | 预制体操作 |
| **Material** | `manage_material` | 材质创建/修改/分配 |
| | `manage_texture` | 程序化纹理生成 |
| **UI** | `manage_ui` | UI Toolkit (UXML/USS/UIDocument) |
| **Editor** | `manage_editor` | Play/Pause/Stop、Tag/Layer 管理 |
| | `execute_menu_item` | 执行菜单项 |
| | `read_console` | 读取/清除控制台 |
| **Testing** | `run_tests` | 启动测试 |
| | `get_test_job` | 轮询测试结果 |
| **Search** | `find_in_file` | 正则搜索文件内容 |
| **Custom** | `execute_custom_tool` | 执行项目自定义工具 |
| **Camera** | `manage_camera` | 相机 + Cinemachine 管理 |
| **Graphics** | `manage_graphics` | Volume/烘焙/管线/URP Features |
| **Package** | `manage_packages` | UPM 包管理 |
| **Physics** | `manage_physics` | 3D/2D 物理全面管理 |
| **ProBuilder** | `manage_probuilder` | ProBuilder 网格操作 |
| **Profiler** | `manage_profiler` | Profiler/内存快照/Frame Debugger |
| **Docs** | `unity_reflect` | 反射检查 Unity C# API |
| | `unity_docs` | 获取官方文档 |

## 传输协议

使用 **MCP Streamable HTTP + SSE** 传输（协议版本 `2024-11-05`）：
- POST JSON-RPC 到 `/mcp` 端点
- 响应为 `text/event-stream` (Server-Sent Events)
- 通过 `mcp-session-id` 头维护会话

## 工具组

部分工具组默认禁用，需通过 `manage_tools` 启用或在 `data/config/unity_mcp.yaml` 中配置：

- `docs` — unity_reflect, unity_docs
- `profiling` — manage_profiler
- `testing` — run_tests, get_test_job
- `physics` — manage_physics
- `probuilder` — manage_probuilder
- `graphics` — manage_graphics
- `camera` — manage_camera
- `packages` — manage_packages

## 文件结构

```
src/tools/builtin/unity/
├── __init__.py          # 聚合导出 (ALL_TOOLS, TOOL_MAP)
├── _mcp.py             # MCP 连接池 (Streamable HTTP + SSE)
├── batch_execute.py    # Infrastructure
├── set_active_instance.py
├── refresh_unity.py
├── manage_tools.py
├── manage_scene.py     # Scene
├── find_gameobjects.py
├── manage_gameobject.py # GameObject
├── manage_components.py
├── create_script.py    # Script
├── script_apply_edits.py
├── apply_text_edits.py
├── validate_script.py
├── get_sha.py
├── delete_script.py
├── manage_asset.py     # Asset
├── manage_prefabs.py
├── manage_material.py  # Material & Shader
├── manage_texture.py
├── manage_ui.py        # UI
├── manage_editor.py    # Editor Control
├── execute_menu_item.py
├── read_console.py
├── run_tests.py        # Testing
├── get_test_job.py
├── find_in_file.py     # Search
├── execute_custom_tool.py # Custom
├── manage_camera.py    # Camera
├── manage_graphics.py  # Graphics
├── manage_packages.py  # Package
├── manage_physics.py   # Physics
├── manage_probuilder.py # ProBuilder
├── manage_profiler.py  # Profiler
├── unity_reflect.py    # Docs
└── unity_docs.py
```

## 参考文档

- [Unity MCP 官方工具参考](https://github.com/CoplayDev/unity-mcp/blob/beta/unity-mcp-skill/references/tools-reference.md)
- [MCP 协议规范](https://spec.modelcontextprotocol.io/)
- 本地副本: `data/unity_mcp_tools_ref.md`
