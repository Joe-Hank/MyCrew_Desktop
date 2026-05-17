import { useEffect, useMemo, useRef, useState } from "react";
import type { CodeContract, Task } from "../../queries/useProjectQuery";
import { useTaskIO, useSubIO } from "../../queries/useWorkflowQuery";
import { usePrefsStore } from "../../stores/usePrefsStore";

type IoTab = "in" | "out" | "contract";

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
  stepIndex,
  onClose,
}: {
  task: Task;
  initialDirection: "in" | "out";
  /** PM v4: when set, the viewer reads the Crew sub-step's IO instead
   *  of the parent task's. The 'in/out' tab maps to the corresponding
   *  field on the sub_io response. */
  stepIndex?: number;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<IoTab>(initialDirection);
  const isSubStep = stepIndex !== undefined && stepIndex !== null;
  // Only call the IO queries when the active tab actually needs them.
  // Contract tab reads task.code_contract synchronously — no fetch.
  const ioTab: "in" | "out" = tab === "contract" ? "out" : tab;
  const { data: taskIo, isLoading: taskLoading } = useTaskIO(
    isSubStep || tab === "contract" ? null : task.id,
    ioTab,
  );
  const { data: subIo, isLoading: subLoading } = useSubIO(
    isSubStep && tab !== "contract" ? task.id : null,
    isSubStep && tab !== "contract" ? stepIndex! : null,
  );
  const io = isSubStep
    ? (subIo
        ? {
            direction: ioTab,
            structured: ioTab === "in" ? subIo.in : subIo.out,
            // Pick the tab-specific raw markdown. `raw_in` / `raw_out`
            // landed 2026-05-17 — the legacy `raw` field served the
            // OUT md regardless of tab, which is exactly the bug being
            // fixed here (input tab showing output's raw).
            raw: ioTab === "in"
              ? (subIo.raw_in ?? null)
              : (subIo.raw_out ?? subIo.raw ?? null),
          }
        : null)
    : taskIo;
  const isLoading = tab === "contract"
    ? false
    : (isSubStep ? subLoading : taskLoading);

  // PM v5: parse task.code_contract once per task — stored as a JSON
  // string in the row. Null / parse failure → no contract to show.
  const contract = useMemo<CodeContract | null>(() => {
    const raw = task.code_contract;
    if (!raw) return null;
    if (typeof raw !== "string") return null;
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed as CodeContract : null;
    } catch {
      return null;
    }
  }, [task.code_contract]);
  const hasContract = !!contract;

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
        {/* PM v5: contract tab only appears for code tasks (the column
            is NULL for Art / Audio / pure-prefab tasks). Hides itself
            cleanly without disabling the layout for the common case. */}
        {hasContract && (
          <TabBtn
            label="代码契约"
            active={tab === "contract"}
            onClick={() => setTab("contract")}
          />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-3">
        {tab === "contract" && contract && (
          <ContractView contract={contract} />
        )}

        {tab !== "contract" && isLoading && (
          <div
            className="py-8 text-center text-xs"
            style={{ color: "var(--color-ink-faint)" }}
          >
            加载中...
          </div>
        )}

        {tab !== "contract" && !isLoading && !io?.structured && !io?.raw && (
          <div
            className="py-8 text-center text-xs"
            style={{ color: "var(--color-ink-faint)" }}
          >
            暂无{tab === "in" ? "输入" : "输出"}数据
          </div>
        )}

        {tab !== "contract" && !isLoading && io?.structured && (
          <div className="mb-3">
            <h4
              className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--color-ink-ghost)" }}
            >
              结构化数据
            </h4>
            <pre
              className="rounded p-3 text-[12px] leading-relaxed"
              style={{
                backgroundColor: "var(--color-card-alt)",
                color: "var(--color-ink)",
                border: "1px solid var(--color-border-soft)",
                // Wrap long lines to the drawer's current width — avoids
                // horizontal scrolling and tracks the user-dragged width.
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                overflowWrap: "anywhere",
              }}
            >
              {JSON.stringify(io.structured, null, 2)}
            </pre>
          </div>
        )}

        {tab !== "contract" && !isLoading && io?.raw && (
          <div>
            <h4
              className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--color-ink-ghost)" }}
            >
              {tab === "in" ? "原始输入" : "原始输出"}
            </h4>
            <pre
              className="rounded p-3 text-[12px] leading-relaxed"
              style={{
                backgroundColor: "var(--color-card-alt)",
                color: "var(--color-ink)",
                border: "1px solid var(--color-border-soft)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                overflowWrap: "anywhere",
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

/** Render task.code_contract — PM v5 named-symbol contract.
 *
 *  Layout mirrors the .mycrew/code_contract.md style:
 *    - one heading per .cs file
 *    - a 2-column table of (kind / signature) per export
 *    - imports section at the bottom listing cross-task symbol pulls
 *
 *  Read-only by design. Editing the contract requires re-running the
 *  PM iterate flow; opening the IO viewer should make that clear by
 *  framing the panel as a reference, not a workspace. */
function ContractView({ contract }: { contract: CodeContract }) {
  const files = contract.files ?? [];
  const imports = contract.imports ?? [];
  return (
    <div className="flex flex-col gap-4">
      <div
        className="rounded p-2 text-[11px] leading-relaxed"
        style={{
          backgroundColor: "rgba(99, 102, 241, 0.08)",
          color: "var(--color-ink-muted)",
          border: "1px solid rgba(99, 102, 241, 0.2)",
        }}
      >
        PM v5 在规划时为这个任务钉死了下列公共符号。
        Crew QA 会逐条 regex 验证生成的 .cs 是否都包含这些签名；
        缺一项 → 任务进 validation_failed。想改 → 走「迭代」让 PM 重跑。
      </div>

      {contract.namespace && (
        <div>
          <h4
            className="mb-1 text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--color-ink-ghost)" }}
          >
            Namespace
          </h4>
          <code
            className="rounded px-1.5 py-0.5 text-[12px]"
            style={{
              backgroundColor: "var(--color-card-alt)",
              color: "var(--color-ink)",
            }}
          >
            {contract.namespace}
          </code>
        </div>
      )}

      {files.length === 0 && (
        <div
          className="py-4 text-center text-xs"
          style={{ color: "var(--color-ink-faint)" }}
        >
          契约为空（PM 标记了非代码任务但仍写了 contract — 异常状态）
        </div>
      )}

      {files.map((f, fi) => (
        <div key={`${f.path}-${fi}`}>
          <div
            className="mb-1.5 flex items-baseline gap-2 text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--color-ink-ghost)" }}
          >
            <span>文件</span>
          </div>
          <code
            className="inline-block break-all rounded px-1.5 py-0.5 text-[12px]"
            style={{
              backgroundColor: "var(--color-card-alt)",
              color: "var(--color-ink)",
            }}
          >
            {f.path}
          </code>
          <ul className="mt-2 flex flex-col gap-1">
            {(f.exports ?? []).map((exp, ei) => (
              <li
                key={ei}
                className="flex items-start gap-2 rounded p-1.5 text-[12px]"
                style={{
                  backgroundColor: "var(--color-card-alt)",
                  border: "1px solid var(--color-border-soft)",
                }}
              >
                <span
                  className="shrink-0 rounded px-1.5 py-0.5 text-[9px] font-medium uppercase"
                  style={{
                    backgroundColor: kindBg(exp.kind),
                    color: kindFg(exp.kind),
                  }}
                >
                  {exp.kind}
                </span>
                <code
                  className="flex-1 break-all"
                  style={{
                    color: "var(--color-ink)",
                    fontFamily: "ui-monospace, SFMono-Regular, monospace",
                  }}
                >
                  {exp.signature}
                </code>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {imports.length > 0 && (
        <div>
          <h4
            className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider"
            style={{ color: "var(--color-ink-ghost)" }}
          >
            依赖（imports — 引用其他任务的符号）
          </h4>
          <ul className="flex flex-col gap-1">
            {imports.map((imp, ii) => (
              <li
                key={ii}
                className="rounded p-2 text-[12px]"
                style={{
                  backgroundColor: "var(--color-card-alt)",
                  border: "1px solid var(--color-border-soft)",
                }}
              >
                <span style={{ color: "var(--color-ink-muted)" }}>
                  来自任务索引 {imp.from_task_index} 的：
                </span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {imp.uses.map((u, ui) => (
                    <code
                      key={ui}
                      className="rounded px-1.5 py-0.5 text-[11px]"
                      style={{
                        backgroundColor: "var(--color-surface-alt)",
                        color: "var(--color-ink)",
                        fontFamily: "ui-monospace, SFMono-Regular, monospace",
                      }}
                    >
                      {u}
                    </code>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Color-code each symbol kind so a scan of the contract list
 *  immediately distinguishes classes / methods / events / fields. */
function kindBg(kind: string): string {
  switch (kind) {
    case "class":
    case "interface":
    case "struct":
    case "enum":
      return "rgba(12, 140, 233, 0.14)";  // brand-ish blue
    case "method":
      return "rgba(99, 102, 241, 0.14)";  // indigo
    case "event":
      return "rgba(245, 158, 11, 0.16)";  // amber
    case "field":
    case "property":
      return "rgba(16, 185, 129, 0.14)";  // emerald
    default:
      return "var(--color-surface-alt)";
  }
}

function kindFg(kind: string): string {
  switch (kind) {
    case "class":
    case "interface":
    case "struct":
    case "enum":
      return "var(--color-brand-500)";
    case "method":
      return "#4f46e5";
    case "event":
      return "#92400e";
    case "field":
    case "property":
      return "#065f46";
    default:
      return "var(--color-ink-muted)";
  }
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
