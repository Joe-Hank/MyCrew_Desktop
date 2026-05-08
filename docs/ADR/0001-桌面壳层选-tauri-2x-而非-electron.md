# 0001. 桌面壳层选 Tauri 2.x 而非 Electron

## Status

Accepted

## Context

MyCrew v2 曾采用 Tauri 作为桌面壳层，但该版本最终被放弃。经过复盘分析，v2 失败的根本原因在于前后端紧耦合以及 sidecar 集成经验不足，而非 Tauri 框架本身的问题。

在选型阶段，我们对比了两个主流桌面应用框架：

| 维度 | Tauri 2.x | Electron |
|------|-----------|----------|
| 打包体积 | ~10 MB | ~80 MB |
| 内存占用 | 较低（系统 WebView） | 较高（自带 Chromium） |
| 安全模型 | 严格的权限白名单 | 较宽松，需手动加固 |
| 生态成熟度 | 中等，快速增长中 | 非常成熟，插件丰富 |
| 后端语言 | Rust | Node.js |

Tauri 2.x（2025+ 版本）已显著成熟，提供了与 Electron 等价的核心能力：

- **Sidecar 进程管理**：可可靠地启动、监控和停止 Python 后端进程
- **单实例锁（Single-Instance Lock）**：防止用户同时打开多个应用实例
- **Stronghold 凭证存储**：安全存储 API Key 等敏感信息，无需依赖系统钥匙串
- **自动更新（Auto-Update）**：内置更新检查与安装流程

v2 的教训已被充分吸收：本次架构设计中，前端代码（React/Vite/Tailwind）与壳层完全解耦，Tauri 相关代码仅存在于 `src-tauri/` 薄层中。这意味着如果未来确实需要迁移到 Electron 或其他框架，迁移成本主要集中在壳层适配层，而非整个应用。

## Decision

采用 Tauri 2.x 作为 MyCrew v3 的桌面壳层框架。

具体实施要点：

1. **壳层职责最小化**：`src-tauri/` 仅负责窗口管理、系统托盘、sidecar 生命周期、IPC 桥接等壳层职责
2. **前端框架无关**：React/Vite/Tailwind 前端代码不依赖任何 Tauri 特有 API，通过抽象层调用壳层能力
3. **Sidecar 模式**：Python 后端作为 sidecar 进程运行，通过 localhost HTTP/WebSocket 与前端通信
4. **凭证管理**：利用 Tauri Stronghold 插件存储 LLM API Key 等敏感信息

## Consequences

**正面影响：**

- 打包体积约 10 MB，远小于 Electron 的 80 MB，用户下载和安装体验更好
- 更严格的安全模型——默认最小权限，所有系统能力需显式声明
- 更低的运行时内存占用，适合长时间运行的 AI 工作流场景
- Tauri 2.x 是现代桌面应用开发的趋势选择，社区活跃度持续上升

**负面影响：**

- Tauri 生态系统规模仍小于 Electron，部分边缘场景可能缺少现成插件
- 壳层开发需要 Rust 知识，团队需具备基本的 Rust 维护能力
- 系统 WebView 在不同操作系统上可能存在渲染差异（尤其是 Linux 上的 WebKitGTK）

**中性影响：**

- 前端代码保持框架无关性，迁移成本可控
- v2 的 Tauri 经验（包括失败经验）可作为参考，但需注意 2.x 与 1.x 的 API 差异

## References

- plan.md §2（技术栈选型）
- plan.md §3（架构概览 - 壳层与 sidecar 通信）
- plan.md §11.5（未来演进 - 壳层迁移路径）
