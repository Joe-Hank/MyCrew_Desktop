# MyCrew Desktop — 构建与开发指南

## 前置依赖

| 工具 | 版本要求 | 用途 |
|------|----------|------|
| Node.js | ≥ 18 | 前端构建 |
| pnpm | ≥ 8 | 前端包管理 |
| Python | ≥ 3.11 | 后端运行 |
| Rust | ≥ 1.70 | Tauri 编译 |
| cargo-tauri | ≥ 2.0 | Tauri CLI |

## 开发启动

### 1. 安装前端依赖

```bash
cd frontend
pnpm install
```

### 2. 安装后端依赖

```bash
cd backend
pip install -e ".[dev]"
```

### 3. 启动后端（开发模式）

```bash
cd backend
uvicorn bootstrap.app:create_app --factory --host 127.0.0.1 --port 18321 --reload
```

### 4. 启动前端（开发模式）

```bash
cd frontend
pnpm dev
```

前端默认运行在 `http://localhost:5173`，会代理 API 请求到后端 `localhost:18321`。

### 5. Tauri 开发模式（可选）

```bash
cd src-tauri
cargo tauri dev
```

这会同时启动前端 dev server + Tauri 窗口 + Python sidecar。

## 生产构建

### 一键构建

```bash
python scripts/build.py
```

该脚本执行以下步骤：
1. PyInstaller 打包后端为单文件 exe（`backend/dist/mycrew_backend.exe`）
2. 复制 exe 到 `src-tauri/binaries/` 作为 sidecar
3. 执行 `cargo tauri build` 生成安装包

### 手动分步构建

#### 后端打包

```bash
cd backend
pyinstaller mycrew_backend.spec
```

输出：`backend/dist/mycrew_backend.exe`

#### 前端构建

```bash
cd frontend
pnpm build
```

输出：`frontend/dist/`

#### Tauri 打包

```bash
cd src-tauri
cargo tauri build
```

输出：`src-tauri/target/release/bundle/`（含 .msi / .exe 安装包）

## 项目结构

```
MyCrew_v3/
├── frontend/          # React + Vite + TypeScript + Tailwind
├── backend/           # Python FastAPI（sidecar 模式）
│   ├── api/           # HTTP/WS 路由
│   ├── bootstrap/     # 应用启动与依赖注入
│   ├── domain/        # 领域核心（状态机/事件/QA）
│   ├── infra/         # 基础设施（MCP连接池/事件总线/交互端口）
│   ├── ports/         # 端口接口定义
│   ├── services/      # 业务服务层
│   └── src/tools/     # 内置 MCP 包装 Tool
├── src-tauri/         # Tauri 2.x Rust 壳层
├── src/               # 共享资源（agents/crews/tools 定义）
├── data/              # 配置文件
├── scripts/           # 构建脚本
└── docs/              # 文档
```

## 环境变量

复制 `.env.example` 为 `.env` 并填写：

```env
MYCREW_DB_PATH=./data/mycrew.db
MYCREW_LOG_LEVEL=INFO
```

LLM API Key 和 MCP 配置通过应用内设置页管理，存储在 SQLite 数据库中。

## 常用命令

| 命令 | 说明 |
|------|------|
| `cd frontend && pnpm dev` | 前端开发服务器 |
| `cd frontend && pnpm build` | 前端生产构建 |
| `cd frontend && npx tsc --noEmit` | TypeScript 类型检查 |
| `cd frontend && pnpm test` | Vitest 单元测试 |
| `cd backend && pytest` | 后端测试 |
| `python scripts/build.py` | 一键打包 |

## 故障排查

### 后端启动失败
- 检查 Python 版本 ≥ 3.11
- 确认 `pip install -e ".[dev]"` 已执行
- 检查端口 18321 是否被占用

### Tauri 编译失败
- 确认 Rust toolchain 已安装（`rustup show`）
- Windows 需要 Visual Studio Build Tools
- 确认 `cargo-tauri` CLI 已安装（`cargo install tauri-cli`）

### 前端类型错误
- 运行 `npx tsc --noEmit` 查看具体错误
- 确认 `pnpm install` 已执行
