# frontend/src/components/settings/

设置页（LLM / MCP / 系统权限三 Tab）。

## 组件清单

| 组件 | 职责 |
|---|---|
| `LlmList.tsx` | LLM Provider 列表；顶部双默认设置器（立项默认 / Agent 默认） |
| `McpList.tsx` | MCP 服务器列表 |
| `PermissionMatrix.tsx` | 9 个布尔开关矩阵 |
| `EditorDrawer.tsx` | 左侧编辑抽屉（多形态：LlmForm / McpForm） |

## LLM 表单

- 一条记录 = 一组 provider+key，下挂一对多 model
- **基础**：名称 / 类型（枚举：openai / anthropic / qwen / deepseek / gemini / ollama / custom） / API Key（掩码） / Base URL
- **模型清单**（嵌入式多行编辑器）：每行 = `model_name`（自由文本）+ 显示标签 + max_tokens + supports_thinking
- Key 入库：前端 `invoke('secret_set', {...})` → Rust 主进程 Stronghold；前端只见掩码

## LLM 选择控件（复用）

- 二级下拉【Provider 记录 → 该 provider 下的某个 model】
- 出现在：Agent 表单、立项对话顶部、其他需要选 LLM 处

## 双默认 LLM

- LLM Tab 顶部两个独立默认设置器
- 存于 `app_settings`：`default_inception_model` / `default_agent_model`
- 用户随时改

## MCP 表单（"协议"字段切换字段集）

- **基础**：名称 / 协议（stdio / http） / 启用开关 / 自动启动开关
- **stdio**：脚本路径（文件选择器） + Args（动态多行） + Env（动态键值对，可标"敏感"走 Stronghold）
- **http**：URL + Headers（动态键值对，可标"敏感"）
- **公共**：超时（秒，默认 30） / 重连退避策略（指数/固定）

## 系统权限（PermissionMatrix）

9 个全局布尔开关：
- 文件读取 / 文件写入 / 文件删除 / 文件修改
- 文件夹读取 / 目录创建
- 命令执行 / 后台命令 / Git 操作

默认全开（保证开箱即用）。**当前为个人单机使用，不限路径不弹审批**——仅在 Tool/MCP 真正调用时按"是否被禁用"短路返回。

未来对外开放时的硬化路线（参 plan §11.5 备注，不在 MVP）。
