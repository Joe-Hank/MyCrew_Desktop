# src-tauri/src/

Tauri Rust 壳层源码。

## 文件清单（Phase 1 创建）

| 文件 | 职责 |
|---|---|
| `main.rs` | App 入口；`tauri::Builder` 装配；单实例锁；菜单/托盘 |
| `sidecar.rs` | Python sidecar 生命周期（`Command::new_sidecar` + 端口探测/握手 + stdout/stderr 转发 + 健康检查 + 退出码监听 + 指数退避重启） |
| `commands.rs` | `#[tauri::command]` 函数集合：`pick_file` / `open_external` / `get_version` / `secret_set` / `secret_get` / `get_backend_port` |
| `lifecycle.rs` | 监听 `WindowEvent::CloseRequested` → 调用后端 `/lifecycle/state` → 弹运行中确认 → 协调 shutdown sequence |

## 关键设计

- **业务隔离**：本目录所有 Rust 代码不接触业务，仅做"本地能力 + 进程编排"
- **凭证主进程独占**：Stronghold 实例只在主进程内持有，前端通过 `invoke('secret_get'/'secret_set')` 访问；Python sidecar 通过 loopback HTTP + 一次性 token 拉取
- **崩溃自愈**：sidecar 退出码 ≠ 0 时指数退避重启（最多 3 次），超阈值后弹错误页 + 导出诊断包

## 测试

- `cargo test`（Phase 1 起补充单元测试 - Mock sidecar 进程行为）
- IPC 集成测试套件由 `tests/` E2E 覆盖
