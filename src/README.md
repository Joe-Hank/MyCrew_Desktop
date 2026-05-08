# src/

**用户可扩展源代码区**。运行时被 backend 扫描加载。

> 区别于其他项目的 `src/`：本目录**不是项目源代码**。Tauri Rust 源在 `src-tauri/src/`，前端源在 `frontend/src/`，后端源在 `backend/`。本目录是用户/开发者**编写自定义 Tool / Agent / Crew** 的地方。

## 子目录

| 子目录 | 内容 | 加载方式 |
|---|---|---|
| `tools/` | 用户自定义 Tool 脚本（CrewAI BaseTool 子类） | 启动期 + 用户在团队页点"扫描" |
| `agents/` | （可选）用户预置 Agent 模板 YAML | Phase 7+ 决定，详见各子目录 README |
| `crews/` | （可选）用户预置 Crew 编排 YAML | Phase 7+ 决定 |

## 关键约束

- 本目录的代码运行在 sidecar 进程内，**没有独立沙箱**（个人单机定位）
- 文件操作受 `permission_svc` 9 个权限开关短路控制
- 首次发现新脚本时弹"信任并加载"二次确认；checksum 变更后再次弹窗
- 未来对外开放时（plan §11.5 硬化路线），用 subprocess + 资源限制再加一层
