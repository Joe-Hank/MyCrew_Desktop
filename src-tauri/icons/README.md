# src-tauri/icons/

应用图标资源，由 Tauri 在打包时引用。

## 规范

需要提供以下尺寸的 PNG（透明背景）：

- 32x32.png
- 128x128.png
- 128x128@2x.png（256x256 实际像素）
- icon.icns（macOS，可选）
- icon.ico（Windows，多分辨率合一）

## 待办

- [ ] 设计师产出 logo 主图（Phase 0 / Phase 9 任一阶段）
- [ ] 用 `cargo tauri icon` 命令从单张高分辨率源图（≥1024x1024）批量生成
- [ ] 检查 `tauri.conf.json` 中 `bundle.icon` 字段引用了正确文件名

## 占位

Phase 0 可暂用 Tauri 默认图标，待视觉资产就绪后再替换。
