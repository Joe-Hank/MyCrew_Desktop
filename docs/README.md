# docs/

项目文档。

## 子目录与关键文件

| 路径 | 内容 | 谁产出 |
|---|---|---|
| `ARCHITECTURE.md` | 架构定稿（plan.md 裁剪后版本） | Phase 0 |
| `API.md` | REST + WS 契约（含 OpenAPI 引用） | Phase 1 起持续更新 |
| `BUILD.md` | 开发启动 + 打包流程 | Phase 0 / Phase 9 |
| `USER_GUIDE.md` | 首次使用 / LLM&MCP 配置 / 故障排查 | Phase 9 |
| `ADR/` | 架构决策记录（001~008 起） | Phase 0 起持续 |
| `dev-notes/` | 各阶段开发记录、调试笔记、踩坑 | 持续 |

## 文档生命周期

- **plan.md**（项目根）—— 设计阶段的权威产物，含完整决策与背景；**冻结后不再修改**，作为历史记录
- **docs/ARCHITECTURE.md** —— plan.md 的"使用版"，去掉过程性描述，是日常开发参考；**会随实施演进**

## 写作约定

- Markdown CommonMark；中文为主
- 代码块带语言标注
- 文件路径用 \`backtick\` 包裹
- 跨文档引用用相对链接

## 版本

文档更新时不必版本号，但重要变更应在文件头部加"最后更新"日期 + 简短变更说明。
