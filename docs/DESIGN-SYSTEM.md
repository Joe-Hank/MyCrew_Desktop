# MyCrew 前端设计系统

> 经过 N 轮迭代沉淀的视觉语言 + 组件参数 + 反复踩过的坑。
> 适用：MyCrew 当前产品 + 未来要做的同系列产品（Tauri/Electron 桌面 + React + Tailwind v4）。
> 读者：人 + AI（Brain / Claude Code 等）。

---

## 0. 设计基调

- **macOS / iOS 现代审美**：圆角 pill、毛玻璃感的浮层、overlay 滚动条、滑动开关
- **克制的色彩**：默认场景一片中性灰白 + 单一品牌蓝点缀；语义色（绿成功、红错误、黄警告）只在状态点出现
- **强烈的层级感**：所有可交互元素都有 hover / active / disabled 三态
- **暗色模式同等对待**：不是后期补丁，是核心设计目标；任何硬编码颜色都被视为 bug

---

## 1. Design Tokens（核心，复制即可用）

### 1.1 颜色（在 `globals.css` 的 `@theme` 块里）

```css
/* 品牌蓝 — 50→900 满阶 */
--color-brand-500: #0c8ce9;   /* 主色：按钮、激活、选中 */
--color-brand-50:  #e6f3fc;   /* 最浅，用作 hover 底色 */
/* 同时把 Tailwind 的 blue-* 全部重映射到这套 brand，
   原有的 `bg-blue-500` 等类自动跟随品牌 */

/* 浅色中性 */
--color-surface:        #f5f7fa;   /* 页面背景 */
--color-surface-alt:    #ededed;   /* 状态栏 / 弹窗底色 / toggle 轨道 */
--color-card:           #ffffff;   /* 卡片、模态、active pill 滑块 */
--color-card-alt:       #fcfcfc;   /* 卡片内的二级背景（表单输入框等） */
--color-border-soft:    #e6e6e6;   /* 主分隔 */
--color-border-strong:  #d7d7d7;   /* 强分隔 / focus ring */

/* 文字 — 7 阶递进，从最深到最浅 */
--color-ink-strong:    #2b2b2b;   /* logo, page heading */
--color-ink:           #363636;   /* 默认正文 */
--color-ink-soft:      #3e3e3e;   /* 卡片标题 */
--color-ink-label:     #4e4e4e;   /* 表单 label, 按钮文字 */
--color-ink-muted:     #697395;   /* 副标题, 未激活 nav */
--color-ink-faint:     #737373;   /* 占位、计数 */
--color-ink-disabled:  #8f8f8f;   /* 禁用态 */
--color-ink-ghost:     #b3b3b3;   /* 极淡 hint, 表头 */

/* 状态色（不进文字色阶，独立使用） */
绿色 #10b981  → 成功、允许、Power-ON 状态
红色 #ef4444  → 错误、危险、stalled
黄色 #f59e0b  → 警告、需要介入
警告底  rgba(245, 158, 11, 0.12)  + 文字 #92400e
```

### 1.2 暗色覆盖（`:root.dark`）

```css
--color-surface:       #0d0f12;
--color-surface-alt:   #1a1d22;
--color-card:          #16181d;   /* ← 关键：active pill 滑块也用这个 */
--color-card-alt:      #1c1f25;
--color-border-soft:   #2a2d33;
--color-border-strong: #3a3d44;

--color-ink-strong:    #f3f4f6;
--color-ink:           #e5e7eb;
/* ...ink scale 全部反转，越向下越淡 */
```

**关键策略**：暗色模式同时**重映射 Tailwind 原生 zinc 色阶**，让组件里硬编码的 `bg-white` / `bg-zinc-100` 等自动跟随：

```css
:root.dark {
  --color-white: #16181d;       /* bg-white → 暗色 card */
  --color-zinc-50:  #1a1d22;    /* hover:bg-zinc-50 → surface-alt */
  --color-zinc-100: #1c1f25;    /* hover:bg-zinc-100 → card-alt */
  --color-zinc-900: #f3f4f6;    /* text-zinc-900 → 亮色文字 */
  /* …完整反转 50→950 */
}
```

> ⚠️ **大坑**：因为 zinc 被反转，`dark:bg-zinc-900` 这种"显式深色"类**会反向显示**（变成亮色）。规则：**所有需要主题感知的颜色都用 `var(--color-*)`，绝不用 `dark:` 前缀**。详见 §6。

### 1.3 字体

```css
--font-sans: "Inter", "Noto Sans SC", "Noto Sans JP",
             system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
```

- Inter 处理英文/数字
- Noto Sans SC 处理中文（项目主语言）
- Noto Sans JP 处理日文
- 系统字体兜底

字号阶（Tailwind 类）：`text-[10px]` → `text-[11px]` → `text-xs` (12) → `text-sm` (14) → `text-base` (16) → `text-lg` → `text-xl`

- 表头 / 角标 / 时间戳 / 占位提示：**10-11px**
- 表格内容 / 描述文字：**12px (text-xs)**
- 正文 / 按钮：**14px (text-sm)**
- 卡片标题：**14-16px**

### 1.4 圆角

| 用途 | 类 | 像素 |
|---|---|---|
| 按钮 / 输入框 | `rounded` / `rounded-md` | 4-6px |
| 卡片 / 模态 / 抽屉 | `rounded-lg` | 8px |
| 项目卡片（更柔和） | `rounded-[10px]` | 10px |
| Pill tabs / Toggle / Tag | `rounded-full` | 全圆 |
| 抽屉根容器 | `rounded-2xl` | 16px |

### 1.5 间距

间距走 Tailwind 默认（4px 步进）：

- **元素内 padding**：`px-2/py-1`（紧凑）, `px-4/py-2`（标准按钮）, `px-5/py-3`（行）
- **元素间 gap**：`gap-1`（密集，工具栏图标）, `gap-2`（默认）, `gap-3`（卡片间）
- **页面四周**：`px-6 pb-3 pt-4`（统一）

### 1.6 阴影

```css
/* 卡片默认 — 几乎不可见，仅做轻微悬浮 */
boxShadow: "0 1px 2px rgba(0,0,0,0.04)"

/* 卡片 hover */
boxShadow: "0 4px 12px rgba(0,0,0,0.08)" (通过 hover:shadow-md)

/* 浮层 / 弹窗 */
boxShadow: "0 10px 25px rgba(0,0,0,0.10)" (通过 shadow-xl)

/* 状态光环（动画在 §4） */
running:  pulse blue rgba(12,140,233, 0.22 → 0.42)
stalled:  static red rgba(239,68,68, 0.45)
loaded:   static blue rgba(12,140,233, 0.30)
```

---

## 2. 暗色模式策略

**核心**：CSS 变量驱动，避免逐组件加 `dark:` 类。

| 用法 | 推荐 | 反例 |
|---|---|---|
| 卡片背景 | `style={{ backgroundColor: "var(--color-card)" }}` | `className="bg-white"` |
| 字体颜色 | `style={{ color: "var(--color-ink)" }}` | `className="text-zinc-900"` |
| 边框 | `style={{ border: "1px solid var(--color-border-soft)" }}` | `className="border-zinc-200"` |
| hover 底色 | `className="hover:bg-zinc-50"` (zinc 被重映射，可接受) | `dark:hover:bg-zinc-800` (重复) |

**唯一例外**：`className="bg-white dark:bg-[var(--color-card)]"` 这种**仅在大块容器**（如 Sidebar）才用，且都明确写好暗色 fallback。

---

## 3. 组件库

### 3.1 主品牌按钮

```tsx
<button
  className="rounded-2xl px-5 py-2 text-sm font-medium text-white
             shadow-sm transition-opacity hover:opacity-90
             disabled:opacity-40 disabled:cursor-not-allowed"
  style={{ backgroundColor: "var(--color-brand-500)" }}
>
  开始
</button>
```

变体：
- **次级**：`backgroundColor: "var(--color-card-alt)" / color: "var(--color-ink-label)" / border 1px var(--color-border-soft)`
- **危险**：`backgroundColor: "#fda4af"` 浅红 + 白字（绝不深红，太刺激）
- **图标按钮**：`rounded p-1 hover:bg-zinc-100`，icon 14-16px

### 3.2 表格（统一模式）

```tsx
const GRID = "grid-cols-[1.4fr_2.5fr_0.8fr_60px]";
// 规则：
//   - 内容列用 fr 比例（按内容长度排序：最长的 fr 最大）
//   - 最右 actions 列永远 60px 固定（容纳 RowActionsMenu 的 ⋯ 按钮）
//   - 中间状态/toggle 列用较小 fr（0.6-0.8）

<div className="overflow-hidden rounded-xl bg-white"
     style={{ border: "1px solid var(--color-border-soft)" }}>
  {/* Header */}
  <div className={`grid ${GRID} items-center gap-2 px-5 py-3`}
       style={{ borderBottom: "1px solid var(--color-border-soft)" }}>
    {[...].map((c) => (
      <span className="text-xs" style={{ color: "var(--color-ink-ghost)" }}>{c}</span>
    ))}
  </div>
  {/* Rows */}
  {items.map((it) => (
    <div className={`group grid ${GRID} items-center gap-2 px-5 py-3
                     transition-colors hover:bg-zinc-50`}
         style={{ borderTop: "1px solid var(--color-border-soft)" }}>
      {/* cells */}
    </div>
  ))}
</div>
```

**重要 ⚠️**：fr 列会**吃光剩余空间**，不要给 actions 列 fr 否则它会被推到行最右导致空旷。看 AgentsTable / ToolsTable / CrewsTable 是同一模式。

### 3.3 Pill Tabs（PillTabs.tsx）

水平 pill 分类条，自带主题感知的滑块：

```tsx
<div className="inline-flex items-center gap-1 rounded-full p-1"
     style={{ backgroundColor: "var(--color-surface-alt)" }}>
  {tabs.map((t) => (
    <button className="rounded-full px-4 py-1.5 text-sm font-medium transition-all"
            style={{
              backgroundColor: isActive ? "var(--color-card)" : "transparent",
              color: isActive ? "var(--color-brand-500)" : "var(--color-ink-muted)",
              boxShadow: isActive ? "0 1px 2px rgba(0,0,0,0.06)" : "none",
            }}>
      {t.label}
    </button>
  ))}
</div>
```

- 轨道 `surface-alt`，激活态用 `card`（明暗自动跟随）
- 激活态文字用品牌色
- 微阴影提升

### 3.4 Toggle 三件套

**3.4.1 标准 on/off**（AgentsTable 思考模式、PermissionTable 权限开关）：

```tsx
// 标准尺寸 24×44px（thinking mode 类）
className="relative inline-flex h-6 w-11 items-center rounded-full"
背景: on ? "#10b981" : "var(--color-surface-alt)"
滑块: absolute h-5 w-5 rounded-full bg-white shadow-sm transition-transform
      transform: on ? "translateX(24px)" : "translateX(2px)"

// 精致尺寸 20×36px（permission 等密集行）
h-5 w-9，滑块 h-4 w-4，translateX 18px/2px
OFF 加边: border: "1px solid var(--color-border-soft)"
ON 加微光: boxShadow: "0 0 0 1px rgba(16,185,129, 0.15)"
```

**3.4.2 双标签 segmented**（链式/层式、ThemeToggle 日月）：

```tsx
const SEG_W = 34;
<span className="relative inline-flex items-center rounded-full p-0.5"
      style={{ width: SEG_W*2 + 4, height: 24,
               backgroundColor: "var(--color-surface-alt)" }}>
  {/* 滑动白色指示器 */}
  <span className="absolute top-0.5 left-0.5 rounded-full bg-white shadow-sm
                   transition-transform duration-200"
        style={{ width: SEG_W, height: 20,
                 transform: isB ? `translateX(${SEG_W}px)` : "translateX(0)" }} />
  {/* 两个标签层叠在上 */}
  <span className="relative z-10 flex items-center justify-center
                   text-[11px] font-medium transition-colors"
        style={{ width: SEG_W,
                 color: isB ? "var(--color-ink-disabled)" : "var(--color-ink)" }}>
    A
  </span>
  <span ...同样模式但反向...>B</span>
</span>
```

- 滑块在底层，标签上层
- 激活侧文字 `--color-ink`，未激活 `--color-ink-disabled`
- 200ms ease 过渡

**3.4.3 大型主题切换**（Sidebar 日月）：同 3.4.2 但 72×36px、SEG_W=30，标签换 icon（sun/moon SVG，stroke 跟随 active 状态变化）

### 3.5 卡片光环（项目状态可视化）

```css
/* keyframe — 蓝色 pulse，用于 running */
@keyframes mc-running-pulse {
  0%, 100% { box-shadow: 0 0 14px 2px rgba(12,140,233, 0.22); }
  50%      { box-shadow: 0 0 22px 4px rgba(12,140,233, 0.42); }
}
.card-halo-running { animation: mc-running-pulse 1.8s ease-in-out infinite; }

/* 任务节点的小一号变体 */
.task-halo-running { /* 1.6s, 8-14px spread */ }
.task-halo-stalled { box-shadow: 0 0 12px 2px rgba(239,68,68, 0.45); }
```

**状态决策树**（项目卡片 / 任务节点通用）：
- `running` + 真在跑（is_running=true）→ 蓝色 pulse 动画
- `stalled` 或 `running` 但 is_running=false → 红色静态光
- 终态 + 用户已载入（lastProjectId 匹配）→ 蓝色静态光（"已打开"标识）
- 其他（ready, pending, ready_to_continue, completed 未打开）→ 无光

### 3.6 卡片选择面板（ChoicePanel）

```tsx
// 2 列网格选项
<div className="grid grid-cols-2 gap-2">
  {options.map((opt) => (
    <button onClick={() => setSelected(opt.value)}
            className="rounded-md p-3 text-left text-xs transition-all"
            style={{
              backgroundColor: isSelected ? "var(--color-brand-500)" : "var(--color-card-alt)",
              color: isSelected ? "#ffffff" : "var(--color-ink-label)",
              border: isSelected ? "1px solid var(--color-brand-500)"
                                 : "1px solid var(--color-border-soft)",
              boxShadow: isSelected ? "0 0 0 3px rgba(12,140,233, 0.18)" : "none",
            }}>
      <div className="mb-1 text-sm font-semibold">{opt.label}</div>
      <div className="text-[11px] leading-snug" style={{ opacity: 0.65 }}>
        {opt.description}
      </div>
    </button>
  ))}
</div>
{/* 二次确认 */}
{selected && <button>确认</button>}
```

- 选中：品牌色填充 + 3px 0.18 alpha brand 外圈（focus-ring 效果）
- 描述文字 11px + 0.65 opacity
- 必须二次确认才锁定 → 转 readonly 模式

### 3.7 输入框

```tsx
<input className="w-full rounded-md px-3 py-1.5 text-sm outline-none"
       style={{
         backgroundColor: "var(--color-card-alt)",
         border: "1px solid var(--color-border-soft)",
         color: "var(--color-ink)",
       }} />
```

- 输入框背景用 `card-alt`（比卡片底色稍浅一点）
- 字号 `text-sm`，行号字 `text-xs`
- 单行 / 多行（textarea）都用同套样式

### 3.8 模态框 / 抽屉

```tsx
{/* 背景遮罩 */}
<div className="fixed inset-0 z-50 flex items-center justify-center"
     style={{ backgroundColor: "rgba(0,0,0,0.4)" }}>
  {/* 内容 */}
  <div className="flex max-h-[88vh] w-full max-w-lg flex-col rounded-lg shadow-xl"
       style={{
         backgroundColor: "var(--color-card)",
         border: "1px solid var(--color-border-soft)",
         color: "var(--color-ink)",
       }}>
    {/* Header */}
    <div className="px-5 py-3" style={{ borderBottom: "1px solid var(--color-border-soft)" }}>
      <h3 className="text-sm font-semibold" style={{ color: "var(--color-ink-soft)" }}>
        标题
      </h3>
    </div>
    {/* Body */}
    <div className="space-y-4 overflow-y-auto px-5 py-4"> ... </div>
    {/* Footer 按钮组 */}
    <div className="flex justify-end gap-2 px-5 py-3"
         style={{ borderTop: "1px solid var(--color-border-soft)" }}>
      <button>取消</button>
      <button>保存</button>
    </div>
  </div>
</div>
```

- 遮罩固定 `rgba(0,0,0,0.4)`
- 标准宽度 `max-w-lg` (512px) / `max-w-2xl` (672px) / `max-w-4xl` (896px)
- 高度上限 `max-h-[88vh]` 留呼吸空间

### 3.9 可拖拽宽度面板（IoViewerDrawer 模式）

```tsx
// 左缘 6px 拖拽热区
<div
  onPointerDown={(e) => {
    dragRef.current = { startX: e.clientX, startWidth: width };
    e.currentTarget.setPointerCapture(e.pointerId);
  }}
  onPointerMove={(e) => {
    if (!dragRef.current) return;
    const dx = dragRef.current.startX - e.clientX; // 右锚定面板
    setWidth(dragRef.current.startWidth + dx);
  }}
  className="absolute left-0 top-0 z-10 h-full w-1.5 cursor-col-resize"
  style={{ touchAction: "none" }}
>
  <div className="absolute left-0 top-0 h-full w-px"
       style={{ backgroundColor: "var(--color-border-soft)" }} />
</div>
```

宽度持久化到 `usePrefsStore`，clamp 280-1200px。

### 3.10 标签/Tag/Chip

```tsx
{/* 小标签（任务状态等） */}
<span className="rounded px-1.5 py-0.5 text-[10px]"
      style={{ backgroundColor: "var(--color-surface-alt)",
               color: "var(--color-ink-muted)" }}>
  待指定
</span>

{/* 主色标签 */}
<span className="rounded-full px-2 py-0.5 text-[11px]"
      style={{ backgroundColor: "var(--color-brand-500)", color: "#ffffff" }}>
  Plan Maker
</span>

{/* 警告标签 */}
<span className="rounded px-1.5 py-0.5 text-[10px]"
      style={{ backgroundColor: "rgba(245,158,11, 0.18)", color: "#92400e" }}>
  QA
</span>
```

### 3.11 RowActionsMenu（⋯ 按钮）

通用模式：每个表行最右一个 ⋯ 按钮 → 点击弹 portal 浮层（不要内嵌避免被 overflow 裁剪）+ 自动判断上下方向（视口下方空间不足就上弹）。详见 `components/common/RowActionsMenu.tsx`。

---

## 4. 动画约定

| 用途 | 时长 | easing |
|---|---|---|
| Toggle 滑块平移 | 200ms | `ease-in-out` |
| 卡片光环 pulse | 1.6-1.8s | `ease-in-out infinite` |
| Pill 切换 | 200ms | `ease`（默认 transition） |
| Hover 颜色变化 | `transition-colors` | 默认 200ms |
| 模态淡入 | 不做（直接 mount/unmount） | — |
| Loading 三个跳点 | `animate-bounce` + `animationDelay` 0/150/300ms | — |

**禁忌**：超过 300ms 的过渡（除非是 hero 动效）；超过 2s 的循环动画。

---

## 5. 滚动条

全局应用 macOS overlay 风格（在 globals.css）：

- thin 风格 (Firefox `scrollbar-width: thin`)
- WebKit thumb 用 `background-clip: content-box` + 2px 透明 border → 视觉上 6px 宽的圆角条
- 暗色模式自动反转 thumb 颜色
- 隐藏角落方块 + 上下箭头

**复用时直接 copy globals.css 第 116-185 行**。

---

## 6. 反复踩过的坑（必读）

### 6.1 `bg-white` 在暗色模式下变白
**症状**：active 滑块 / 卡片在夜间模式显示纯白，扎眼。
**根因**：Tailwind v4 加 zinc 反转后，`white` 也被 remap 成 dark surface，但**有些代码硬编码 `backgroundColor: "white"`** 绕过了 token 系统。
**修法**：所有需要主题感知的颜色用 `var(--color-card)` / `var(--color-card-alt)`。**绝不写 `"white"` / `"#fff"` 字面量**。

### 6.2 `dark:bg-zinc-900` 反向显示
**症状**：写 `bg-white dark:bg-zinc-900` 期望"亮 → 白，暗 → 深"，实际"亮 → 透明，暗 → 浅灰"。
**根因**：globals.css `:root.dark` 把 `--color-zinc-900` 反转成 `#f3f4f6`（亮色）；同时 `--color-white` 在亮色模式没定义 → 透明。
**修法**：弃用 `dark:` 前缀，全部用 `style={{ backgroundColor: "var(--color-card)" }}`。

### 6.3 Grid `fr` 列把固定列挤到边缘
**症状**：表格里 toggle / actions 显示在远右边，看起来很空。
**根因**：`fr` 列会**吃光所有剩余空间**，固定 px 列被推到最右。
**修法 A**（推荐）：所有非 actions 列用 fr，actions 用 60px 固定 ← 这是表格标准
**修法 B**：用 `minmax(min, max)` 限制最大宽 + 故意让行右侧留白
**反例**：`grid-cols-[1.4fr_2fr_70px_60px]` 会让 70px 看起来很靠右

### 6.4 RowActionsMenu 被 overflow 裁剪
**症状**：表格最后一行的 ⋯ 弹窗被 `overflow-hidden` 切掉。
**修法**：弹窗用 `createPortal(menu, document.body)` 渲染到 body + 通过 `getBoundingClientRect` 计算位置 + 视口空间不足时自动上弹。

### 6.5 流式消息抖动
**症状**：聊天流式输出时画布 / 节点 / 边重渲染抖动。
**根因**：每次 refetch 重建 nodes/edges 数组身份。
**修法**：节点用 smart-merge（保留 position + identity）；边数组用 `depsKey`（拼接所有 deps 字符串）作 memo 依赖。

### 6.6 Tailwind v4 任意值类不更新
**症状**：改 `grid-cols-[1fr_2fr_...]` 后 Vite HMR 没反应。
**修法**：硬刷新（Ctrl+Shift+R），或重启 vite dev server。Tailwind v4 的 JIT 偶尔漏新增的任意类。

### 6.7 按钮 vs Toggle vs Switch 命名混乱
- **Button** = 一次性动作（保存、删除）
- **Toggle** = 二态开关，立即生效（权限开/关、主题切换）
- **Pill Tabs** = N 选 1 视图切换
- **Choice Panel** = N 选 1 + 二次确认（重决策、不可瞬间改）
- **Segmented Control** = 双标签 toggle（链式/层式、日/月）

---

## 7. 组件库索引

### 共享（components/common/）
- `PillTabs.tsx` — 主题感知的水平 pill 分类
- `RowActionsMenu.tsx` — ⋯ portal 浮层
- `SideDrawer.tsx` — 通用侧抽屉壳
- `AutoTextarea.tsx` — 自适应行数的 textarea（10 行上限）
- `QueryErrorState.tsx` — 数据加载失败时的统一空态

### 布局（components/layout/）
- `Sidebar.tsx` — 110px 左侧导航 + Logo + ThemeToggle + 版本 + 连接点
- `AppShell.tsx` — 路由外壳
- `LogDrawer.tsx` — 底部日志抽屉（展开/收起，underline-style tabs）

### Inception 流（components/inception/）
- `InceptionDrawer.tsx` — Plan Maker 对话抽屉
- `ChoicePanel.tsx` — 卡片选择（带二次确认 + readonly 历史）
- `PathInputPanel.tsx` — 路径输入（带浏览按钮 Tauri dialog）
- `TaskBlueprintEditor.tsx` — 任务图编辑器

### Task 页（components/task/）
- `CanvasBlueprint.tsx` — @xyflow/react 画布
- `TaskNode.tsx` — 200px 节点卡片（运行 pulse / stalled 红 halo）
- `IoViewerDrawer.tsx` — 拖拽宽度的 IO 查看器
- `TaskEditModal.tsx` — 任务编辑模态
- `TaskHeader.tsx` — 任务页顶栏（进度 + pause/resume）

### 首页（components/home/）
- `ProjectCard.tsx` — 项目卡片（halo + 收藏 + 迭代 + 删除）
- `ProjectGrid.tsx` — 分页网格
- `StatusBars.tsx` — 顶部 token quota bar

### 团队 / 设置（components/team/, components/settings/）
- `AgentsTable.tsx` / `CrewsTable.tsx` / `ToolsTable.tsx`
- `LlmTable.tsx` / `McpTable.tsx` / `PermissionTable.tsx`
- `TeamEditorDrawer.tsx` / `SettingsEditorDrawer.tsx`

---

## 8. 复用到新项目的清单

新建桌面/Web 产品时：

1. **复制 `globals.css`** 整个文件（209 行包括 tokens + dark + scrollbars + halo keyframes）
2. **保留 `--font-sans` 链**（Inter + Noto SC + 系统兜底）
3. **复制 `usePrefsStore.ts` 的骨架**（zustand persist + 主题、tab、宽度等）
4. **复制 `useThemeStore.ts` 与 `applyTheme()` 函数**（class-based dark toggle，挂载到 `:root.dark`）
5. **照搬 §3 组件库**：每个组件代码量都 <100 行，复制 + 改文案即可
6. **避坑清单**：每次写新组件之前过一遍 §6
7. **`docs/STORAGE-MAP.md`** 模板也搬过去 — 文档先行，不然半年后没人记得数据放哪

---

## 9. 设计原则速查

- 任何颜色硬编码（`#ffffff`、`white`、`#000` 等）= bug
- 任何 `dark:` 类 = 优先考虑改成 CSS 变量
- 任何 fr 列在 actions 旁边 = 重排成 fixed
- 任何 `>300ms` 的过渡 = 重新评估
- 任何 overflow-hidden 容器里的弹层 = 用 portal
- 任何二态选择 = 用 toggle，不要用 select
- 任何 N 选 1 = pill tabs 或 choice panel，不要用 select
- 任何"白色背景"在审计中 = 想想暗色模式

---

## 10. 变更须知

新增组件 / 调整 token 时必须更新本文档；commit message 前缀 `docs(design):`。
