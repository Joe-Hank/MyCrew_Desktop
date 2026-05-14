import { useEffect, useRef, useState } from "react";
import type { Task } from "../../queries/useProjectQuery";
import { useTaskIO } from "../../queries/useWorkflowQuery";
import { usePrefsStore } from "../../stores/usePrefsStore";

/** Side drawer that shows a task's input + output payloads (structured
 *  JSON and raw text). The user can drag the left edge to widen / narrow
 *  it; the chosen width is persisted via usePrefsStore so subsequent
 *  opens land at the same size.
 *
 *  Theming uses our `--color-*` CSS variables (defined in @theme and
 *  inverted in :root.dark) instead of Tailwind's `dark:` prefix —
 *  globals.css inverts Tailwind's zinc scale under :root.dark, so the
 *  naive `bg-white dark:bg-zinc-900` pattern produces inverted colours
 *  (light drawer in dark mode and vice-versa). Same root cause as
 *  TaskEditModal's note. */
function IoViewerDrawer({
  task,
  initialDirection,
  onClose,
}: {
  task: Task;
  initialDirection: "in" | "out";
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"in" | "out">(initialDirection);
  const { data: io, isLoading } = useTaskIO(task.id, tab);

  const width = usePrefsStore((s) => s.ioViewerWidth);
  const setWidth = usePrefsStore((s) => s.setIoViewerWidth);

  // ── Drag-to-resize ─────────────────────────────────────────────
  // Pointer events keep the drag active even when the cursor leaves
  // the handle (vs. mouse events). The drag is anchored at startX +
  // startWidth so the drawer width follows the cursor without jitter.
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  function handlePointerDown(e: React.PointerEvent<HTMLDivElement>) {
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startWidth: width };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }
  function handlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return;
    // Drawer is right-anchored — dragging left expands it.
    const dx = dragRef.current.startX - e.clientX;
    setWidth(dragRef.current.startWidth + dx);
  }
  function handlePointerUp(e: React.PointerEvent<HTMLDivElement>) {
    dragRef.current = null;
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
  }

  // ESC closes the drawer (parity with TaskEditModal)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="relative flex h-full flex-col"
      style={{
        width,
        backgroundColor: "var(--color-card)",
        borderLeft: "1px solid var(--color-border-soft)",
        color: "var(--color-ink)",
      }}
    >
      {/* Left-edge drag handle. The visible 1px guideline lives inside
          a 6px hit-zone so the cursor catches it without precision. */}
      <div
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        className="absolute left-0 top-0 z-10 h-full w-1.5 cursor-col-resize"
        style={{ touchAction: "none" }}
        title="拖动调整宽度"
      >
        <div
          className="absolute left-0 top-0 h-full w-px transition-colors hover:bg-current"
          style={{
            backgroundColor: "var(--color-border-soft)",
            color: "var(--color-brand-500)",
          }}
        />
      </div>

      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-2.5"
        style={{ borderBottom: "1px solid var(--color-border-soft)" }}
      >
        <div className="flex items-center gap-2">
          <span
            className="text-xs font-semibold"
            style={{ color: "var(--color-ink-soft)" }}
          >
            IO 查看器
          </span>
          <span
            className="rounded px-1.5 py-0.5 text-[10px]"
            style={{
              backgroundColor: "var(--color-surface-alt)",
              color: "var(--color-ink-muted)",
            }}
          >
            {task.title}
          </span>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 transition-colors hover:bg-zinc-100"
          style={{ color: "var(--color-ink-ghost)" }}
          title="关闭 (Esc)"
        >
          ✕
        </button>
      </div>

      {/* Tabs */}
      <div className="flex" style={{ borderBottom: "1px solid var(--color-border-soft)" }}>
        <TabBtn label="输入" active={tab === "in"} onClick={() => setTab("in")} />
        <TabBtn label="输出" active={tab === "out"} onClick={() => setTab("out")} />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-3">
        {isLoading && (
          <div
            className="py-8 text-center text-xs"
            style={{ color: "var(--color-ink-faint)" }}
          >
            加载中...
          </div>
        )}

        {!isLoading && !io?.structured && !io?.raw && (
          <div
            className="py-8 text-center text-xs"
            style={{ color: "var(--color-ink-faint)" }}
          >
            暂无{tab === "in" ? "输入" : "输出"}数据
          </div>
        )}

        {!isLoading && io?.structured && (
          <div className="mb-3">
            <h4
              className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--color-ink-ghost)" }}
            >
              结构化数据
            </h4>
            <pre
              className="overflow-x-auto rounded p-3 text-[12px] leading-relaxed"
              style={{
                backgroundColor: "var(--color-card-alt)",
                color: "var(--color-ink)",
                border: "1px solid var(--color-border-soft)",
              }}
            >
              {JSON.stringify(io.structured, null, 2)}
            </pre>
          </div>
        )}

        {!isLoading && io?.raw && (
          <div>
            <h4
              className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--color-ink-ghost)" }}
            >
              原始输出
            </h4>
            <pre
              className="whitespace-pre-wrap break-words rounded p-3 text-[12px] leading-relaxed"
              style={{
                backgroundColor: "var(--color-card-alt)",
                color: "var(--color-ink)",
                border: "1px solid var(--color-border-soft)",
              }}
            >
              {io.raw}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

function TabBtn({
  label, active, onClick,
}: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex-1 py-2 text-xs font-medium transition-colors"
      style={{
        color: active ? "var(--color-brand-500)" : "var(--color-ink-faint)",
        borderBottom: active
          ? "2px solid var(--color-brand-500)"
          : "2px solid transparent",
      }}
    >
      {label}
    </button>
  );
}

export default IoViewerDrawer;
