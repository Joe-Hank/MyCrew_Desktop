import { type ReactNode, useEffect } from "react";

/**
 * Left-side overlay drawer used for "new entry" / "edit entry" forms on Team & Settings pages.
 * Per Figma: ~1/3 screen width, grey background, semi-transparent black overlay covers the rest.
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
    <div className="fixed inset-0 z-40 flex">
      {/* Drawer body (left, ~1/3) */}
      <div
        className="flex h-full w-[420px] max-w-[40%] flex-col shadow-2xl"
        style={{ backgroundColor: "var(--color-surface-alt)" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4">
          <h2 className="text-base font-semibold" style={{ color: "var(--color-ink-strong)" }}>
            {title}
          </h2>
          {onReset && (
            <button
              onClick={onReset}
              className="rounded p-1 transition-colors hover:bg-white/50"
              style={{ color: "var(--color-ink-muted)" }}
              title="重置"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round">
                <polyline points="23 4 23 10 17 10" />
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
              </svg>
            </button>
          )}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto px-5 pb-4">{children}</div>

        {/* Footer */}
        {footer && <div className="px-5 pb-5">{footer}</div>}
      </div>

      {/* Right side dim backdrop */}
      <button
        onClick={onClose}
        className="flex-1 cursor-default"
        style={{ backgroundColor: "rgba(0, 0, 0, 0.35)" }}
        aria-label="关闭"
      />
    </div>
  );
}

export default SideDrawer;

/** Drawer footer with standard cancel + save buttons. */
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
        className="rounded-lg bg-white px-6 py-2.5 text-sm transition-colors hover:bg-zinc-50"
        style={{
          color: "var(--color-ink-label)",
          border: "1px solid var(--color-border-soft)",
        }}
      >
        取消
      </button>
      <button
        onClick={onSave}
        disabled={saving || saveDisabled}
        className="flex-1 rounded-lg py-2.5 text-sm font-medium text-white transition-opacity disabled:opacity-50"
        style={{ backgroundColor: "var(--color-brand-500)" }}
      >
        {saving ? "保存中..." : saveLabel}
      </button>
    </div>
  );
}

/** Standard form field with left label */
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
        className="mt-2 w-12 shrink-0 text-sm"
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

export const inputCls =
  "w-full rounded-lg bg-white px-3 py-2 text-sm outline-none transition-colors focus:bg-zinc-50";
