import { type ReactNode, useEffect } from "react";

/**
 * Centred modal used for "new entry" / "edit entry" forms on Team & Settings
 * pages. Per user spec:
 *   - Fixed width (480px), auto-height up to 88vh, scrolls internally beyond
 *   - Sits over a dim full-screen backdrop
 *   - ESC + backdrop click close
 *
 * The component is still named `SideDrawer` for now to avoid churning every
 * import site; the rendering shape changed from "left-pinned slide-in panel"
 * to "centred modal" without breaking the public API ({title, open, onClose,
 * onReset, footer, children}).
 */
function SideDrawer({
  title,
  open,
  onClose,
  onReset,
  footer,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  onReset?: () => void;
  footer?: ReactNode;
  children: ReactNode;
}) {
  useEffect(() => {
    function onEsc(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    if (open) document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.45)" }}
      onClick={onClose}
      role="presentation"
    >
      {/* Modal body. Stop click propagation so clicks inside don't close. */}
      <div
        className="flex max-h-[88vh] w-[480px] flex-col rounded-xl shadow-2xl"
        style={{
          backgroundColor: "var(--color-card)",
          border: "1px solid var(--color-border-soft)",
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ borderBottom: "1px solid var(--color-border-soft)" }}
        >
          <h2 className="text-base font-semibold" style={{ color: "var(--color-ink-strong)" }}>
            {title}
          </h2>
          <div className="flex items-center gap-1">
            {onReset && (
              <button
                onClick={onReset}
                className="rounded p-1 transition-colors hover:bg-zinc-100"
                style={{ color: "var(--color-ink-muted)" }}
                title="重置"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="23 4 23 10 17 10" />
                  <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                </svg>
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded p-1 transition-colors hover:bg-zinc-100"
              style={{ color: "var(--color-ink-muted)" }}
              title="关闭"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* Body — auto-height; scrolls internally past max-h-[88vh]. */}
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {/* Footer */}
        {footer && (
          <div
            className="px-5 py-3"
            style={{ borderTop: "1px solid var(--color-border-soft)" }}
          >
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export default SideDrawer;

/** Standard cancel + save row used at the bottom of the modal. */
export function DrawerFooter({
  onCancel,
  onSave,
  saving,
  saveDisabled,
  saveLabel = "保存",
}: {
  onCancel: () => void;
  onSave: () => void;
  saving?: boolean;
  saveDisabled?: boolean;
  saveLabel?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <button
        onClick={onCancel}
        className="rounded-lg px-5 py-2 text-sm transition-colors hover:bg-zinc-100"
        style={{
          color: "var(--color-ink-label)",
          backgroundColor: "var(--color-card)",
          border: "1px solid var(--color-border-soft)",
        }}
      >
        取消
      </button>
      <button
        onClick={onSave}
        disabled={saving || saveDisabled}
        className="flex-1 rounded-lg py-2 text-sm font-medium text-white transition-opacity disabled:opacity-50"
        style={{ backgroundColor: "var(--color-brand-500)" }}
      >
        {saving ? "保存中..." : saveLabel}
      </button>
    </div>
  );
}

/** Form field row with a left label + right control. */
export function FormField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start gap-4">
      <label
        className="mt-2 w-14 shrink-0 text-sm"
        style={{ color: "var(--color-ink-label)" }}
      >
        {label}
      </label>
      <div className="min-w-0 flex-1">
        {children}
        {hint && (
          <p className="mt-1 text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
            {hint}
          </p>
        )}
      </div>
    </div>
  );
}

/** Standard input className. Background + border use CSS variables so the
 *  control stays readable in both light and dark themes (Tailwind v4 +
 *  globals.css' zinc-inversion remap made the old `bg-white focus:bg-zinc-50`
 *  invert in dark mode — see TaskEditModal for the same fix). */
export const inputCls =
  "w-full rounded-lg px-3 py-2 text-sm outline-none transition-colors";

/** Inline style companion to `inputCls` — apply both to keep colour
 *  decisions in one place. */
export const inputStyle: React.CSSProperties = {
  backgroundColor: "var(--color-card-alt)",
  border: "1px solid var(--color-border-soft)",
  color: "var(--color-ink)",
};
