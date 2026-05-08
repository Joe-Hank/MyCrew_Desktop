# frontend/src/components/ui/

通用 UI Kit。基于 Shadcn/ui copy-in 模式（不作为 npm 依赖，按需 copy 文件进来）。

## 组件清单（按需扩展）

| 组件 | 用途 |
|---|---|
| `Button.tsx` | 主/次/危险态按钮 |
| `Modal.tsx` | 模态对话框（复用：删除二次确认 / rerun 二次确认 / 强制中断确认 / 关窗运行中确认） |
| `Drawer.tsx` | 通用抽屉（黄金分割宽度，可拖拽记忆） |
| `Toast.tsx` | 全局通知（顶部，含优先级与堆叠） |
| `StatusDot.tsx` | 状态指示点（绿/黄/红/灰） |
| `Empty.tsx` | 空状态占位 |
| `Skeleton.tsx` | 加载骨架 |
| `Tabs.tsx` | Tab 切换（团队/设置页用） |
| `Form/*` | 表单基础（Input / Select / Switch / TagsInput） |

## 使用约定

- 通过 `npx shadcn@latest add <component>` 添加新组件
- 添加后允许按需修改（这是 shadcn 的设计哲学）
- Tailwind class 直接写在组件内；不用 styled-components / emotion

## 主题

- 使用 CSS 变量（`--background` / `--foreground` 等）
- 日夜切换通过 `<html data-theme="dark">` 切根属性
