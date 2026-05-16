# MyCrew v3

CrewAI + MCP 的本地服务窗口（PC 桌面应用）。单机运行，无云部署需求。

## 核心能力

1. 维护并实时监控多个 MCP 服务器的连接状态
2. 接入多家 LLM API（Claude / OpenAI / Qwen 等）
3. 通过 CrewAI 编排多 Agent 协作工作流
4. 项目进度自由管理（DAG、暂停、断点续跑、人工介入）
5. 对话驱动的项目立项
6. 插件化扩展（用户在 `src/tools/` 放置脚本即可被 Agent 调用）

## 技术栈

| 层 | 选型 |
|---|---|
| 桌面壳 | Tauri 2.x（Rust） |
| 前端 | React 19 + Vite 6 + TypeScript 5 + Tailwind 4 + Shadcn/ui |
| 状态管理 | React Query（服务端态）+ Zustand（UI 态） |
| 后端 | FastAPI + Uvicorn（Python sidecar）|
| Crew 引擎 | CrewAI |
| 持久化 | SQLite + aiosqlite + Alembic 迁移 |
| 凭证 | tauri-plugin-stronghold + DPAPI 回退 |
| 打包 | PyInstaller（后端） + Tauri build（NSIS / MSI） |

## 目录速览

```
MyCrew_v3/
├─ src-tauri/    Tauri Rust 壳层（窗口/sidecar/凭证）
├─ frontend/     React WebView（4 页面：主页/任务/团队/设置）
├─ backend/      Python sidecar（api/services/domain/ports/infra）
├─ src/          用户可扩展（tools/agents/crews）
├─ data/         运行时数据（config/db/logs/cache/secrets/runtime）
├─ output/       项目运行产物
├─ docs/         架构文档与 ADR
├─ scripts/      启停/打包/迁移脚本
├─ tests/        E2E 测试（Playwright）
└─ assets/       静态资源
```

## 文档入口

- [docs/README.md](./docs/README.md) — 文档总索引（spec / iterations / roadmap / ADR / archive 分类）
- [plan.md](./plan.md) — 初始架构与实施路线图（**已冻结**；演进版见 `docs/spec/ARCHITECTURE.md`）
- [docs/spec/ARCHITECTURE.md](./docs/spec/ARCHITECTURE.md) — 架构定稿（跟代码同步演进）
- [docs/spec/API.md](./docs/spec/API.md) — REST + WS 契约
- [docs/ADR/](./docs/ADR/) — 关键架构决策记录
- [docs/iterations/](./docs/iterations/) — 按日期归档的迭代日志
- [docs/roadmap/](./docs/roadmap/) — 未来规划 + 设计草案（含 MCP / OpenClaw 集成预案）

## 快速开始

```bash
# 前置：Node.js 24+, pnpm 11+, Rust 1.95+, Python 3.12+

# 安装前端依赖
cd frontend && pnpm install && cd ..

# 创建 Python 虚拟环境并安装后端依赖
cd backend && python -m venv .venv && .venv\Scripts\pip install -e ".[dev]" && cd ..

# 启动开发模式（Tauri 会同时拉起 Vite 和 Rust 窗口）
cd src-tauri && cargo tauri dev
```

详情参见 [plan.md](./plan.md)。

## License

[MIT](./LICENSE)
