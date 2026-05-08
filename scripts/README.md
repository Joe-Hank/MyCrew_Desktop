# scripts/

启停 / 打包 / 数据库迁移 / 类型生成等工程脚本。

## 脚本清单（按 phase 落地）

| 文件 | 用途 | Phase |
|---|---|---|
| `dev.ps1` / `dev.sh` | 一键启动开发模式（并发跑 Vite + Tauri + uvicorn） | Phase 0 |
| `build.ps1` / `build.sh` | 完整打包：PyInstaller → Tauri build → NSIS / MSI | Phase 9 |
| `gen-types.ts` | 后端 OpenAPI JSON → 前端 TS 类型 | Phase 1 |
| `test-migration.sh` | Alembic 三联回环验证（upgrade head → downgrade -1 → upgrade head） | Phase 1 |
| `ipc-integration.ps1` | IPC 集成测试套件（spawn / 崩溃 / shutdown / MCP 关闭信号 / migration） | Phase 1 |
| `lint-all.sh` | ESLint + Ruff + cargo fmt 全跑 | Phase 0 |
| `clean.ps1` | 清理 dist/build/node_modules/target/.venv | Phase 0 |
| `init-data.ps1` | 重置 data/db/ + 重跑迁移（开发期清测试数据用） | Phase 1 |

## 执行约定

- Windows 用 PowerShell（`.ps1`），跨平台脚本用 Node 或 Python（`.ts` / `.py`）
- bash 脚本 (`*.sh`) 仅在 git bash / WSL 下用
- 所有脚本必须能在仓库根目录直接执行，不依赖特定工作目录

## 待添加

- 凭证导入/导出脚本（Phase 2 后）
- 备份恢复脚本（Phase 7 后）
