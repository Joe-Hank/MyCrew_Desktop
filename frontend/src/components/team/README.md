# frontend/src/components/team/

团队页（Agents / Crews / Tools 三 Tab）。

## 组件清单

| 组件 | 职责 |
|---|---|
| `AgentList.tsx` | Agent 卡片列表，每行显示关键信息 + 操作按钮（编辑/删除）；自动生成的带 `auto-generated` 徽章 |
| `CrewList.tsx` | Crew 列表 |
| `ToolList.tsx` | Tool 列表；按 `source(builtin\|user)` 分组；MCP 包装 Tool 子目录的标题行显示"已包装 K / 已发现 N"，未包装的灰色文字列出 + "生成包装骨架"按钮 |
| `EditorDrawer.tsx` | 左侧黄金分割编辑抽屉；多形态（AgentForm / CrewForm / ToolForm）；右上角重置 + 取消 + 保存 |

## 表单字段（与设置页 LLM/MCP 表单结构一致）

### Agent 表单
- 角色名 / 目标 / 背景
- 能力：enable_reasoning / max_retry / memory_enabled + memory_path / thinking_mode（仅当所选 LLM model 支持）
- 工具（多选自 Tools tab，包含手写 MCP 包装 Tool）
- LLM（二级下拉：provider → model）
- **不绑 MCP 服务器**：MCP 服务器仅作为"后台资源"启用；Agent 通过手写包装 Tool 调用具体 MCP 工具

### Crew 表单
- 队名 / 过程（sequential / hierarchical 标"实验性"） / 角色（多选 Agent）

### Tool 表单
- 提示文案"建议将脚本统一放在 `<MyCrew 根目录>/src/tools/` 下"
- 名称 / 脚本路径（带"扫描 src/tools"快捷按钮） / 来源标记（builtin / user）

## 加载安全

- 首次发现新用户 Tool 时弹"信任并加载"二次确认
- checksum 变更后再次弹窗
