# tests/

端到端测试（Playwright）。

> 注意：单元/集成测试在各模块本地（`backend/tests/`、`frontend/src/**/*.test.tsx`）。本目录仅放 E2E。

## 工具

- **Playwright**：驱动 Tauri 应用窗口
- **Tauri WebDriver**（`tauri-driver`）：Tauri 应用的 WebDriver 桥

## 测试场景（plan §17.2 + §17.1）

按 plan §17.1 验收标准的 8 项功能闭环至少覆盖：

| 测试文件 | 场景 |
|---|---|
| `01-smoke.spec.ts` | 4 页可切换、关闭无残留进程 |
| `02-config-restore.spec.ts` | 配置录入 → 关闭 → 重开后保留 |
| `03-mcp-status.spec.ts` | MCP 在线/离线切换 → 状态条实时更新 |
| `04-create-project.spec.ts` | 立项对话 → 任务草案编辑 → finalize → 项目卡出现 |
| `05-run-project.spec.ts` | 跑项目（小型）→ DAG 推进 → final_qa → 项目完成 |
| `06-pause-resume.spec.ts` | 运行中暂停 → 恢复继续 |
| `07-failure-intervene.spec.ts` | Task 失败 → 介入对话 → 重试成功 |
| `08-shutdown-recovery.spec.ts` | 项目运行中关窗 → 二次确认 → 重开后恢复 |

## 运行

```bash
# 安装依赖
pnpm install
cd tests && pnpm playwright install

# 跑全部 E2E
pnpm e2e

# 跑单个场景
pnpm e2e tests/05-run-project.spec.ts

# 调试模式（headed + slowmo）
pnpm e2e --debug
```

## 与 IPC 集成测试的区别

- **IPC 集成测试**（`scripts/ipc-integration.ps1`）：聚焦 Tauri 主进程 ↔ Python sidecar 的进程间通信稳定性（spawn / 崩溃 / shutdown）
- **E2E 测试**（本目录）：聚焦端到端用户流程（含 UI 交互）

## CI 集成

- IPC 集成测试 + E2E 都是 must-pass（plan §17.2）
- 跑 E2E 时 LLM 调用走 `MYCREW_MOCK=1` 模式（不消耗真实 token）
