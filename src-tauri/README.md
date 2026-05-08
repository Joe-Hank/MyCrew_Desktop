# src-tauri/

Tauri 2.x Rust 壳层。

## 职责

- 应用生命周期、窗口/托盘/菜单
- Python sidecar 进程管理（spawn / 端口握手 / 健康检查 / 崩溃重启）
- 单实例锁（`tauri-plugin-single-instance`）
- 凭证存储（`tauri-plugin-stronghold` + DPAPI 回退）
- 自动更新（`tauri-plugin-updater`，可选）
- Tauri Commands：仅本地能力（选文件 / 打开外链 / 版本号 / 凭证存取）

## 不做

- 不转发业务请求（前端 → HTTP/WS → Python sidecar 直连）
- 不持有业务状态
- 不实现 LLM / MCP / CrewAI 任何业务逻辑

## 子目录

- `src/` Rust 源码
- `icons/` 应用图标（多尺寸 PNG / ICO）
- `binaries/` PyInstaller 产出的后端二进制存放位置（按 Tauri 命名约定 `mycrew-backend-{target-triple}.exe`），开发期可缺失，打包时必须存在

## 关键文件（Phase 0/1 创建）

- `tauri.conf.json` — 窗口尺寸、sidecar 路径、权限 allowlist
- `Cargo.toml` — Rust 依赖（tauri / single-instance / stronghold / updater / reqwest）
- `build.rs` — Tauri 构建脚本
