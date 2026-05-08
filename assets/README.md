# assets/

静态资源。

## 用途

- 应用 Logo / 图标源文件（≥1024x1024 PNG）→ 由 `cargo tauri icon` 生成 `src-tauri/icons/`
- 文档中嵌入的截图、流程图
- 主题预览图等

## 不在此处

- `src-tauri/icons/` —— 已打包到应用的多尺寸图标（由本目录源图生成）
- `frontend/public/` —— 前端构建期内联到 bundle 的资源（如 favicon、字体）
- `output/` —— 项目运行产物（用户数据，不入仓）

## 待确认细节

> 以下属于"未定细节"，等 Phase 0 / Phase 9 设计师介入时再补：

1. **Logo 设计** —— 主图、应用图标、社交分享图（Open Graph）
2. **字体** —— UI 字体选型（系统字体 vs 引入 Inter / Noto Sans CJK）
3. **品牌色板** —— 与 Shadcn 的默认主题协调；CSS 变量值
4. **截图归档** —— 用户引导文档（USER_GUIDE.md）需要的应用截图

## 结构占位

```
assets/
├─ logo/             （Phase 0 / Phase 9 落地）
├─ screenshots/      （Phase 9 落地，配 USER_GUIDE.md）
└─ branding/         （Phase 9 落地）
```

## 当前状态

- 占位
- 留 .gitkeep 防空目录
- 待视觉资产就绪后填充
