# frontend/src/styles/

全局样式 + 主题系统。

## 文件清单（建议）

| 文件 | 用途 |
|---|---|
| `globals.css` | Tailwind base/components/utilities + CSS reset |
| `theme.css` | CSS 变量（日夜两套） |
| `tokens.ts` | 设计 token 的 TS 常量映射（颜色、间距、字号），方便组件内引用 |

## 主题切换实现

> 待 Phase 0 落地后定稿。当前定向：

- 用 `data-theme="dark"` 切换 `<html>` 属性
- CSS 变量在 `:root` 和 `[data-theme="dark"]` 各定义一套
- 用户偏好存 `app_settings.theme`（值：`light` / `dark` / `system`）；启动时读取并应用
- `system` 模式下监听 `prefers-color-scheme` 媒体查询变化

## 待确认细节（Phase 0 实施前可能微调）

- **是否引入 next-themes / nextra 类似的主题库** —— 当前倾向自己写一套（约 30 行代码搞定）；不引第三方依赖
- **Shadcn/ui 默认主题对接** —— shadcn 官方使用 `--background`/`--foreground` 风格的 CSS 变量，本目录约定与之一致以便 copy-in 组件无缝工作
- **过渡动画** —— 切换主题时是否启用 200ms transition？默认启用，但元素较多时可能引发性能问题，需测试

落地时若有进一步决策（如选用某主题库或具体 token 值），追加到本 README 末尾。
